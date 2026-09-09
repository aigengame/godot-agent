# Preview performance sampling

`gda asset-pipeline preview` samples scene-level counters after capturing its final
view. `comparison.status=comparable` means the observed setup and measurement
settings match. It does not establish stable performance, visual equivalence, or
per-mesh GPU cost. Keep genuine low FPS values; use the returned timestamps and
individual samples to interpret mean/p95 changes.

An optional `--warmup-seconds` waits after the final capture and before sampling.
It accepts finite seconds from 0 through 10, defaults to 0, and adds that requested
interval to the invocation. It does not detect equilibrium, wait for a particular
FPS, or make a low sample invalid. A positive completed wait appears as `warmup` in
`preview.completed`. The requested value is in `preview.request.warmup_seconds`;
different values make baselines non-comparable. Existing reports without the
field retain the original zero-wait interpretation.

```sh
gda asset-pipeline preview --path /production/model.glb \
  --output-dir /reports/model-preview --frames 60 --warmup-seconds 2.5 \
  --baseline /reports/prior-preview.json --json
```

Use the same value in both runs. The wait is interruptible, and the existing
owned-session and temporary-project cleanup still applies. It does not change the
readiness timeout or the existing performance request bound. An operating-system
scheduling pause can make wall-clock time longer than requested.

## Investigation for #950

A maintained asymmetric, untextured GLB was measured on Godot 4.6.3 official
`7d41c59c4`, macOS, `gl_compatibility`, at 320 × 180 with 12 sampled process frames.
Three runs for each wait were interleaved. One 400 × 180 control was correctly
non-comparable. All runs stopped their owned session and removed the temporary
project. The same input produced one draw call and 12 primitives per sample.

The initial experiment used a local port wrapper to apply the candidate waits
before adding a public option:

| Wait after captures | FPS means across three runs | Engine sample timestamps | Added wait |
| --- | --- | --- | --- |
| 0 seconds | 1, 1, 1 | 590–961 ms | none |
| 1.25 seconds | 1027, 1039, 1071 | 1829–1848 ms | about 1.25 s |
| 2.5 seconds | 2548, 2578, 2545 | 3088–3097 ms | about 2.50 s |

These values are environment observations, not acceptance thresholds or a model
benchmark. They do not reproduce the exact earlier dogfood values of 7.33/12.67,
and do not establish the sole cause of that earlier variation. They demonstrate
that sampling before and after counter updates can radically change the reported
FPS with unchanged draw/primitive counts. Repeated inputs after a wait still vary.
The 2.5-second wait avoided the initial counter interval here at a visible latency
cost; it is an optional procedure, not a universal recommended duration.

A second ten-run matrix exercised the delivered public option. Zero-wait means
remained 1; both positive-wait groups reported 120 in all three runs. Matching
settings were comparable and the 400-pixel control was non-comparable; all cleanup
checks passed. This substantial change from the first experiment is a further
limit on interpreting timing as a reproducible asset cost. The cause of the
between-matrix rate change was not isolated. Neither matrix establishes a stable
FPS guarantee or justifies changing the zero default.

The engine source explains the sampling distinction: `Performance.TIME_FPS`
[reads the engine FPS counter](https://github.com/godotengine/godot/blob/4.6.3-stable/main/performance.cpp#L237-L242),
which is [updated after accumulated elapsed time exceeds one second](https://github.com/godotengine/godot/blob/4.6.3-stable/main/main.cpp#L5019-L5045).
gda reads that counter on each selected process frame. Twelve samples can therefore
contain twelve copies of one update, rather than twelve independent FPS estimates.
The source also notes that FPS reporting immediately after startup is inaccurate;
this does not authorize discarding a low counter.

Reproduce the fixed matrix through the delivered public option from the repository:

```sh
uv run python -m tests.asset_pipeline.preview_fps_probe --output-dir /tmp/gda-fps-probe
```

The directory must be new. This opt-in investigation writes all public preview
results, captures, raw samples, elapsed times, comparisons and cleanup outcomes;
it does not assert a minimum FPS or run as a benchmark gate in CI. The maintained
native acceptance separately checks that a requested wait occurs before sampling
and that cleanup remains complete.
