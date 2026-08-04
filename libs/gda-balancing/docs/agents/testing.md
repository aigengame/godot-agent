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

| Shard | Main ownership | Local median test time |
| --- | --- | ---: |
| `fast` | policy, lifecycle, resources, migration, and small suites | 41.170 s |
| `authority` | authority CLI and authority bootstrap | 132.534 s |
| `language` | language bootstrap and formula CLI | 85.316 s |
| `model` | model CLI and independent lowerer | 86.394 s |
| `experiment` | experiment CLI | 113.766 s |
| `composition` | CLI conformance, composition bootstrap, and templates | 82.880 s |
| `smoke` | end-to-end CLI paths | 96.557 s |

The figures are medians calculated from the same three post-change full-suite
JUnit reports used below. Shard membership is deliberately static and
reviewable; the existing partition test proves that files neither overlap nor
fall outside the matrix.

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

The remaining largest file medians are experiment CLI (113.766 s), end-to-end
CLI (96.557 s), authority CLI (93.359 s), and language bootstrap (79.369 s).
These values explain the shard split; they are not new test policy.

## CI acceptance

Before #597, three required-CI runs at the clean base took 483 s, 496 s, and
483 s from the scope job start to the stable required check, for a 483 s
median. Record the three exact-head post-change runs and their URLs in the PR.
Acceptance requires a median improvement of at least 25% and no run above six
minutes.

Nightly and release flows are not restructured by this member change. Any
future workflow change must be justified independently by measured CI evidence
and must live in a root-owned, non-releasing PR.
