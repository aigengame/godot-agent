# Public bounded-fold cost observations

These are fixed-source observations for issue #877, not a performance improvement
claim. The recorded implementation is worker commit
`060d0989f544926e7e006de0c3caa016069213b3`; `source-manifest.json` hashes all 124
production Python files. Later admission fixes change the producer fingerprint
truthfully. The recorded machine and each candidate's Kernel, LDB and RIR identities
are in `measurement.json`.

The public program filters a finite List, counts its selected items, and reduces the
original input in order. Measurement candidates change only its nominal List
capacity and derived Operation bound. Global resource limits and Runtime profiles
remain unchanged. Each input has N zeroes; the last-rejected variant replaces the
last zero with 2, under threshold 1. It still eagerly constructs the discarded final
append.

| Capacity | All-selected attempts | Last-rejected attempts |
| --- | ---: | ---: |
| 4 | 52 | 49 |
| 8 | 96 | 93 |
| 16 | 184 | 181 |
| 22 | 250 | 247 |
| 23 | Refuses on attempt 257 | Not measured |

N23 builds and checks successfully. Runtime refuses at
`fold/ordered-items/@22`, instruction 1, under the unchanged Event budget of 256;
its audit reports no committed state. This separates a runtime budget boundary from
an input capacity refusal.

Each successful candidate used three fresh ordinary CLI runs and a fourth,
separately instrumented CLI run. All six artifact members were byte-identical
within each group. Bare wall-time medians were non-monotonic, 1.73–6.39 seconds, on a
shared development host; process peak RSS was approximately 86.7–91.3 MiB. These
measurements include startup, admission and publication. They do not isolate
Runtime latency or establish a scaling trend. CPU user/system time was not recorded.

The additional cProfile/tracemalloc runs cover the complete command, materially
increase its time, and must not be compared as bare latency. Actual append calls
were N. Typed-value validation calls were 1196, 1288, 1568 and 1862 for the four
all-selected capacities. Canonical JSON validation is counted separately.

`append_typed_value` first validates and copies the existing prefix through
`structured_values._validate`, then constructs a new appended List. For these
prefixes, those two constructions alone write N² slots: 16, 64, 256 and 484. Further
argument, result and artifact validation adds work. This is a lower bound on total
copy work, not a claim that live peak memory is quadratic. The new fold does not
remove this copying cost.

## Reproduce

Use the package's installed development dependencies and a fresh output directory:

```sh
python docs/refactor/current-language/evidence/bounded-fold/measure.py --output /path/to/fresh-output
```

The script derives the package root from its own tracked location and reuses the
maintained public-test authority constructor. It copies the production package,
verifies that every Python file is unchanged, seals the private capacity variants,
and invokes the actual CLI through the chosen Python interpreter. It does not
replace an evaluator, increase system budgets or reuse a completed invocation.
Output includes each command's stdout/stderr, authored inputs, artifacts,
`receipt.json`, and separate profile JSON/binary data. The original measurements
used Python 3.13.13 on macOS arm64; a new run records its actual environment and
source hashes. Source or authority changes can truthfully change its identities.

A bounded runner check can use `--capacities 4 --modes all-selected --repeats 1`.
This option still performs build/check plus one bare and one instrumented run; it
is not the original three-sample measurement.

`raw-index.json` records hashes and locations of retained original raw material.
The large artifacts, disposable package copies and profiler binaries are not
embedded here. Temporary raw paths are provenance locations, not script inputs.

`validation.json` records successful real runs of the final portable script for
N4 (bare plus instrumented) and N23 (typed budget refusal), scoped static checks,
and verification of the source manifest and all 162 indexed raw byte contents.

## Final Runtime boundary rerun

`final-runtime-measurement.json` preserves a separate run at
`e5a2aae2295a6c483c1fd536ff52dfe937fd4c73`, including the final post-state
validation fix and physical removal of `Operation.vectors`. It repeats only
N22 all-selected, N22 last-rejected, and N23 all-selected:

```sh
python docs/refactor/current-language/evidence/bounded-fold/measure.py --output /path/to/fresh-output --capacities 22 23 --modes all-selected last-rejected --repeats 3
```

The successful cases still charge exactly 250 and 247 attempts; N23 refuses on
attempt 257 without committing state. Each successful group again has six identical
member artifacts across three bare runs and a separate instrumented run. Full
sample values and profiler counts are recorded, without a speedup claim.

`final-runtime-source-manifest.json` records the five changed source hashes relative
to the historical manifest. `final-runtime-raw-index.json` indexes 159 raw files as
73 unique byte contents, each verified against the retained raw material.

The subsequent oracle seal at `5db4389ab` changes nine authority resource files and
26 expected identity leaves. The audit verifies unchanged production Python,
Kernel bytes, and package semantic closures. Two actual Model builds using the
preserved N22/N23 Source bytes also produce byte-identical RIR payloads under that
seal. This transfers the selected execution rules and bounds; the recorded timing
samples still belong to the measured graph. Full authority identities differ
truthfully, and the original nine-case observations remain unchanged.
