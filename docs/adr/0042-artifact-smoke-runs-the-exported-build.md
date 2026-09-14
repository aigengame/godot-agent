---
status: accepted
---

# The artifact smoke: `gda export smoke` runs the exported build, under the `script run` contract

Every piece of evidence gda produces today runs the PROJECT under the editor binary: a
[Headless operation](../../CONTEXT.md), `gda script run` (ADR-0031), `gda scene preflight`
(#664), and a [Live operation](../../CONTEXT.md) inside an [Engine session](../../CONTEXT.md).
Nothing observes the EXPORTED build. `gda export run` constructs an
[Export artifact](../../CONTEXT.md) and reports the construction — preset, platform, mode,
output path, the directories it created, the engine's warnings — and that result was read as
"releasable" on three candidates of the kung-fu dogfooding project (GDA-DF-072, gda 0.11.0):
the first candidate loaded the whole game and leaked four WAV resources at exit, a defect
observable only by running the exported artifact, which the export's `warnings: []` could not
see. An exported build differs from the project the editor binary runs: it uses the release
template, the PCK holds what the export filters admitted, the harness is stripped (ADR-0028),
and imported resources are remapped. Issue #841 asked for two capabilities — an artifact
report and a declared post-export smoke — and required a scope decision before either was built.

**Narrowed first (2026-09-14, on #841).** Signing observations, bundle metadata, the
architecture list, the exported project's source revision, a deny-network launch and the
"receipt / attestation" framing are OUT: an agent can call `codesign`, `plutil` and `lipo`
itself, so wrapping them adds no agent value (ADR-0025 criterion 1); whether a signature is
valid is the project's release policy, not a fact gda interprets; reading git would be a new
dependency and a new precedent while the artifact hashes already are the identity; auditability
is a non-functional requirement that needs its own case. They entered from one macOS
notarization workflow — a small situation, not a product promise.

**Measured before deciding (Godot 4.6.3 release template, macOS universal, unsigned probe
exported through `gda export run`, 2026-09-14):**

- the exported binary accepts `--headless` and `--log-file` and exits with the script's own
  `quit(N)`; a windowed run works too;
- the release template still prints `push_error`, `push_warning` and BOTH exit-time leak
  records (`ObjectDB instances leaked at exit`, `N resources still in use at exit`) — to
  stderr only: the `--log-file` file never holds the leak records, because the file logger
  closes before the leak detection runs;
- setting `HOME` (the macOS lever of the [User-data placement](../../CONTEXT.md)) redirects
  the exported game's `user://` exactly as it does the editor binary's, the real user directory
  untouched;
- the PCK is a separate `Contents/Resources/<name>.pck` unless the preset embeds it.

## Decision

**gda gains ONE new point on the [Project-code execution surface](../../CONTEXT.md): the
[Artifact smoke](../../CONTEXT.md), `gda export smoke <artifact>`, which runs the exported
game itself.** It is the release-stage leg of the agent's write → run → observe → fix loop
and the only observation of the shipped build. The ADR-0025 test holds on both criteria:
agent value (the defect above was observable nowhere else) and structured-operation fit (a
bounded one-shot run with one `--json` result, a `--schema`, and the existing `GdaError`
envelopes — the shape `script run` already publishes). Trust: the exported game is the
[Trusted project](../../CONTEXT.md)'s own code (ADR-0009); the smoke widens the surface by
one point and adds no trust axis.

1. **Identity lives where the artifact is born.** `export run` reports the artifact's identity
   as additive fields — executable(s) and PCK: path, size, SHA-256; PCK header facts:
   validity, the engine version the header carries, entry count, embedded or separate; the gda
   provenance `gda --version --json` already computes. `pack` mode identifies its bare PCK the
   same way. The smoke ECHOES the identity of what it launched, so a construction result and a
   smoke result correlate by hash. There is no `export verify` command: a read-only re-check of
   an existing artifact is a narrow case, and only the PCK half is knowledge an agent cannot
   get from `shasum`.
2. **Shape: the `script run` contract, verbatim.** `export smoke <artifact>` is a separate
   command under the `export` group (ADR-0019: the artifact is the export domain object;
   ADR-0004: one operation, one result). The positional is the `output_path` `export run`
   reported. Parameters mirror `script run`: repeatable `--arg` passed to the game, `--timeout`,
   `--completion-marker` (ADR-0031's declared liveness contract, whole-line equality), `--strict`;
   plus `--windowed`. The result mirrors `script run`: `exit_status`, the bounded `stdout`
   projection (#665), `stderr` verbatim, `diagnostics` from the shared recognizer, the user-data
   placement (#850), plus the identity echo. The run ending is success and the exit status is
   data; `--strict` fails as `script_failed` on a non-zero exit OR a recognized exit-time leak —
   the same predicate as `script run --strict` (through #976's policy table once it lands). No
   derived `clean` boolean. A project `push_warning` is not in the recognizer's closed set; a
   project that rejects every warning applies that policy over the verbatim `stderr` itself.
3. **Headless by default, `--windowed` opt-in** (the `daemon start` precedent); `user://` goes
   to a fresh private root per run by default, `--user-data-root` names a durable one; gda
   passes `--log-file` so the game writes no rotated default log, and captures stderr because
   that is where the leak records are.
4. **Failure semantics reuse the existing families.** Two new `operation` codes registered
   under ADR-0002: `export_artifact_not_found` (the path is absent) and
   `export_artifact_not_runnable` (a `pack`-mode bare PCK, a bundle with no executable, an
   executable for another platform). Launch failures use the classifiers `script run` uses
   (`launch_timeout` with its evidence clocks, `script_aborted` for the marker's early end).
   The game's own exit status is data unless `--strict`. An identity fact gda cannot read (an
   unparsable PCK header) is null with a reason field — never a failure of the parent result,
   never fabricated; `export run`'s `warnings` keeps its engine-advisory meaning (#839).
5. **Declared on the command line only.** No project-side declaration of the smoke's arguments
   or expectations (no `project.godot` section, no gda config file): ADR-0031's contract
   already gives the caller the arguments, the timeout, the marker and the strict gate.
   `export run --smoke` as composition sugar is possible later and is not decided here.

Left to the implementation slices and their reviews: the field-level shape of the identity
object and its reason field, the PCK header reader, the exact messages of the two codes, the
executable's location per platform (a macOS bundle's `Contents/MacOS/<name>`, a bare
executable elsewhere).

## Considered options

- **Additive smoke on `export run` (`--smoke`), rejected for now.** One result would carry a
  construction and a run; GDA-DF-072 asked for exactly the opposite distinction, and a smoke
  must be re-runnable on an artifact exported earlier without exporting again.
- **A separate read-only `export verify` for the identity facts, rejected.** A narrow case, a
  third command, and most of its facts an agent gets from `shasum`; the identity on `export
  run` plus the echo on the smoke closes the workflow.
- **A smoke-specific "clean" rule (any `ERROR:`/`WARNING:` line fails), rejected.** It would
  fail a release on an engine advisory unrelated to the project and give the agent a second
  verdict vocabulary; the `script run` contract is one thing to learn.
- **Reading the log file instead of stderr, rejected by measurement.** The leak records never
  reach it.
- **Running the artifact with the real `user://`, rejected as the default.** A smoke that
  writes into the developer's save directory is a side effect; `--user-data-root` reaches the
  real one when a smoke needs it.
- **The full artifact report (signing, metadata, architectures, source revision), rejected.**
  Recorded on #841 as the part-1 narrowing above.

## Consequences

- CONTEXT.md gains two terms in the same change — `Export artifact` and `Artifact smoke` — and
  its `Project-code execution surface` entry names the smoke as its widest point: the whole
  exported game, for as long as the caller's timeout allows, on the shipped build rather than
  the project under the editor binary.
- Two follow-up slices are filed from this ADR (`/to-issues`, milestone #12, W5): **S1** the
  identity fields on `export run`, **S2** `export smoke`; S2 is blocked by S1 (the echo) and
  both are serial with #839 on the export command module.
- A smoke launches an executable that is not the Godot editor binary, so the launch is a
  sibling of the [Headless launch](../../CONTEXT.md) primitive with a different argv head
  (the artifact's executable, `--headless` only when not windowed, `--log-file`, the caller's
  arguments); it must reuse the primitive's streaming, timeout, placement and `Raw run`
  normalization rather than copy them.
- The recognizer (`gda.script_errors`) gains a consumer that is not an editor-binary run; its
  closed set and admission rule are unchanged — the release template prints the same records.
- Not promised: the smoke does not sandbox the game, does not deny it the network, and does not
  interpret signing; a project's release portfolio stays the project's.
