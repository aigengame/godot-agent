# Testing and full-suite latency

This page records how to run the gda-balancing test suite and the measured
latency work tracked by
[#597](https://github.com/aigengame/godot-agent/issues/597). It is an
operational guide, not a second test specification.

## Commands

Run the complete member suite from the repository root:

```bash
uv run --frozen --project libs/gda-balancing pytest \
  libs/gda-balancing/tests -q
```

From this package directory, the equivalent command is:

```bash
uv run --frozen pytest tests -q
```

`tools/ci.py` remains the existing authority for CI scope classification,
static shard membership, and inventory closure. Reproduce one shard with:

```bash
uv run --no-project --python 3.13 python \
  libs/gda-balancing/tools/ci.py shard-paths authority |
  xargs uv run --frozen --project libs/gda-balancing pytest -q
```

This optimization adds no local runner, coverage ledger, accepted-test
manifest, or aggregate JUnit protocol. Test preservation is checked by
comparing the complete collection before and after the change. The repository's
pre-existing inventory and outcome checks continue unchanged.

## Existing verification contract

Production publishes one process-scoped, deeply immutable
`AdmittedAuthorityContext` only after the complete packaged Kernel and sealed
Language Definition Bundle graph has loaded, admitted, indexed, and frozen. A
failed admission publishes no partial context. Explicitly injected candidates
are admitted into independently owned contexts, and schema meta-validation is
cached by the actual canonical schema and Kernel profile bytes.

Tests preserve those boundaries:

- `pristine_authority_context` supplies the immutable packaged baseline;
- `mutable_authorities()` is the shared deep-copy helper, and the
  `authority_candidate` fixture builds its candidate from that helper;
- loader, failure-publication, cache, and cold-command tests continue to use
  the dedicated loading and lifecycle seams; and
- Consumer B remains an independent interpreter and does not call production
  admission or schema-cache implementations.

The pre-existing inventory check proves that baseline tests and vectors have
not disappeared and that every current test belongs to exactly one shard. Run
it from the repository root with:

```bash
uv run --frozen --project libs/gda-balancing python \
  libs/gda-balancing/tools/ci.py verify-inventory \
  --report /tmp/gda-balancing-inventory.json
```

`schema2-test-inventory-v1.json` remains the source for baseline test and
vector identities and allowed skips. `schema2-bootstrap-migration-map.json`
remains the mapping for the earlier bootstrap test split. Pytest collection
rejects `xfail(strict=False)` before execution.

CI also runs the existing outcome check on each JUnit file; undeclared skips
and xfails fail the job. Balancing-affecting or unknown paths run inventory,
all six required shards, the separate smoke shard, and the stable
`gda-balancing required` result. Each test process retains the existing
eight-minute bound and fifteen-minute job timeout. Scheduled and release flows
retain their complete unfiltered-suite checks, existing fifteen-minute process
bound, outcome verification, and diagnostic uploads. Member release PRs remain
restricted to `libs/gda-balancing/**`; this change does not alter those
workflows or their ownership boundary.

## Optimizations

Two repeated setup costs were removed without weakening the tested contracts:

- Tests that need mutable Kernel and Language Definition Bundle inputs now
  copy the already admitted packaged authority. Cold-load and lifecycle tests
  continue to use their dedicated loaders.
- The built-wheel authority test still checks the archive bytes, runs the real
  wheel module, and compares every source and wheel result. Its repeated
  `package get` commands now share one wheel process instead of starting one
  process per child.

No test, parameter case, assertion, or packaged vector was removed.

## Static CI shards

The complete suite is partitioned by file. The `smoke` shard remains a separate
real-subprocess and end-to-end job. The other six shards feed the stable
`gda-balancing required` check.

| Shard | Main ownership |
| --- | --- |
| `fast` | policy, lifecycle, authority bootstrap, resources, migration, and small suites |
| `authority` | authority CLI |
| `language` | language bootstrap and formula CLI |
| `model` | model CLI and independent lowerer |
| `experiment` | experiment CLI |
| `composition` | CLI conformance, composition bootstrap, and templates |
| `smoke` | end-to-end CLI paths |

Shard membership is deliberately static and reviewable; the existing partition
test proves that files neither overlap nor fall outside the matrix. The `model`
and `experiment` files are measured indivisible hotspots. Giving each a matrix
entry keeps the largest local required shard near 114 seconds instead of
combining files into partitions near 172 and 197 seconds. The workflow already
derives its matrix from `REQUIRED_TEST_SHARDS`, so the split costs two additional
standard matrix executions but adds no custom runner or new aggregator, timer,
inventory, or artifact protocol. Moving the two independently selectable
bootstrap files to `fast` separates them from the authority CLI hotspot.

## Local evidence

The accepted clean base is commit `2b81e2e`. Each measurement used an already
installed frozen environment and a fresh pytest process. Pytest cumulative
time comes from JUnit; wall time comes from `/usr/bin/time -p`.

| Measurement | Clean base median | Optimized median | Change |
| --- | ---: | ---: | ---: |
| Collected tests | 1,409 | 1,409 | unchanged |
| Pytest cumulative time | 1,292.539 s | 634.676 s | -50.9% |
| Full-suite wall time | 1,297.274 s | 636.840 s | -50.9% |

All three optimized runs collected 1,409 tests and finished with 1,382 passed
and 27 skipped. Their wall times were 636.840 s, 643.920 s, and 632.840 s.

The remaining largest file medians are experiment CLI (about 114 s), end-to-end
CLI (about 97 s), authority CLI (about 93 s), and language bootstrap (about 79 s).
These values explain the shard split; they are not new test policy.

## CI acceptance

Before #597, three required-CI runs at the clean base took 483 s, 496 s, and
483 s from the scope job start to the stable required check, for a 483 s
median. Three successful six-shard runs produced these results:

| Run | Elapsed |
| --- | ---: |
| [Attempt 1](https://github.com/aigengame/godot-agent/actions/runs/30927209932/attempts/1) | 277 s |
| [Attempt 3](https://github.com/aigengame/godot-agent/actions/runs/30927209932/attempts/3) | 268 s |
| [Attempt 4](https://github.com/aigengame/godot-agent/actions/runs/30927209932/attempts/4) | 229 s |

The median was 268 s, a 44.5% improvement, with a 277 s maximum. These runs
establish the accepted six-shard partition. Review-fix heads require ordinary
CI before merge, but unchanged shard membership does not require another
three-run performance sample. #597 uses this fixed comparison; the rolling
20-run p95 protocol introduced with #587 is not a standing gate for this
refactor.

Nightly and release flows are not restructured by this member change. Any
future workflow change must be justified independently by measured CI evidence
and must live in a root-owned, non-releasing PR.
