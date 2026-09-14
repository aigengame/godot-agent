---
status: accepted
---

# The artifact smoke: `gda export smoke` runs a same-host exported game on the shared launch mechanics, with its own policy

Every piece of evidence gda produces today runs the PROJECT under the editor binary: a
[Headless operation](../../CONTEXT.md), `gda script run` (ADR-0031), `gda scene preflight`
(#664), and a [Live operation](../../CONTEXT.md) inside an [Engine session](../../CONTEXT.md).
Nothing runs the [Export artifact](../../CONTEXT.md). `gda export run` constructs one and
reports the construction — preset, platform, mode, output path, the directories it created,
the engine's warnings — and that result was read as "releasable" on three candidates of the
kung-fu dogfooding project (GDA-DF-072, gda 0.11.0). The first candidate loaded the whole game
and leaked four WAV resources at exit. That defect was observable only by running the exported
game, which the export's `warnings: []` could not see. An exported game differs from the
project the editor binary runs: release template, a PCK holding what the export filters
admitted, the harness stripped (ADR-0028), imported resources remapped.

**The need, and nothing more.** The observable user need is: run the exported game on the
host that built it, bounded, and observe its exit status, its stderr and its exit-time leaks.
Issue #841 also asked for an artifact report (hashes, architectures, signing, bundle metadata,
source revision, a receipt). That half was narrowed away on the issue (2026-09-14, part 1) and
its remainder — a content identity of the artifact — was removed in this ADR's second review:
"complete content identity" is a non-functional requirement with no evidence-backed need in
GDA-DF-072, and every attempt to serve it (an executable-plus-PCK model, then a bounded
cross-platform inventory) turned into a platform abstraction that hid platform differences
instead of removing them. A Web export's `output_path` names the `.html` while the exporter
writes the `.pck`, `.wasm` and images as siblings (`platform/web/export/export_plugin.cpp`);
a bounded inventory of "files under the output path" misses them, and two artifacts differing
beyond an inventory cap read identical. No identity contract remains in this decision.

**Measured (Godot 4.6.3 release template, macOS universal, unsigned probe exported through
`gda export run`, 2026-09-14; observations recorded on #841):**

- The exported game accepts `--headless` and `--log-file` and exits with the script's own
  `quit(N)`. A windowed run works too.
- The release template still prints `push_error`, `push_warning` and BOTH exit-time leak
  records (`ObjectDB instances leaked at exit`, `N resources still in use at exit`). The leak
  records reach stderr only; the `--log-file` file never holds them, because the file logger
  closes before the leak detection runs.
- Arguments after Godot's `--` separator reach `OS.get_cmdline_user_args()` and never
  `OS.get_cmdline_args()`. Arguments before it are not refused by an exported game; they land
  in `OS.get_cmdline_args()` beside the engine's own.
- Setting `HOME` (the macOS lever of the [User-data placement](../../CONTEXT.md)) redirects
  the exported game's `user://` exactly as it does the editor binary's; the real user directory
  stays untouched.

Not measured: Linux and Windows hosts. The implementation slice pins what it promises on each
supported host with its own probes.

## Decision

**gda gains ONE separate caller-artifact execution point: the
[Artifact smoke](../../CONTEXT.md), `gda export smoke <artifact>`, which runs a same-host
desktop exported game.** It is not part of the [Project-code execution
surface](../../CONTEXT.md): gda has no fact tying the caller-selected artifact to the resolved
project. It is the release-stage leg of the agent's write → run → observe → fix loop. ADR-0025
holds on both criteria: agent value (the defect above was observable nowhere else) and
structured-operation fit (a bounded one-shot run, one `--json` result, a `--schema`, the
existing `GdaError` envelopes).

### 1. Trust subjects and authority

- The resolved [Trusted project](../../CONTEXT.md) (ADR-0009) is the subject of every point on
  the Project-code execution surface.
- The caller-selected Export artifact is a DISTINCT subject: gda executes it unsandboxed, with
  no verified provenance — gda has no fact to tie the artifact to the project and does not
  claim one. The relation is the one gda already has with `--project`: the caller chooses what
  gda runs.
- This section is the authority for that distinct trust subject; CONTEXT.md refers here rather
  than folding the smoke into the project's "no new trust axis" rule.

### 2. What the smoke is

- Requirement: run the exported game the caller names, bounded, and report what happened.
- Supported: a desktop artifact on its own host — a macOS bundle on macOS, a Linux executable
  on Linux, a Windows executable on Windows. gda locates the executable (a bundle's
  `Contents/MacOS/<name>`, a bare executable elsewhere).
- Refused before launch, two `operation` codes registered under ADR-0002:
  `export_artifact_not_found` (the path is absent) and `export_artifact_not_runnable` (not a
  supported same-host desktop artifact: a bare PCK, a bundle with no executable, a Web,
  Android or iOS output, an executable for another platform). The refusal names what it saw.
  No all-platform model sits behind the refusal; it is a simple typed "not this".
- Parameters: the positional is the `output_path` `export run` reported; repeatable `--arg`;
  `--timeout`; `--completion-marker`; `--strict`; `--windowed`; `--user-data-root`.
- Argv: the executable, `--headless` unless `--windowed`, `--log-file` on a gda-owned path,
  `--`, then every `--arg` value in order — so caller arguments reach
  `OS.get_cmdline_user_args()` and can never be read as engine options.
- Result on a run that ended: `exit_status` (data, never a verdict by itself), the bounded
  `stdout` projection (#665), `stderr` verbatim, `diagnostics` from the shared recognizer over
  the captured stderr (the release template prints the same records), the user-data placement
  (#850), the caller's artifact path, and the resolved executable path plus a SHA-256 computed
  immediately before launch. The digest is a bounded, non-atomic pre-launch observation: it
  lets a reader distinguish the several candidates in GDA-DF-072, but it does not prove what
  bytes the OS executed and is not content identity, a manifest or provenance. The smoke does
  not report a discovered PCK: finding one does not establish which pack Godot loaded.
- Headless by default, `--windowed` opt-in (the `daemon start` precedent). gda passes
  `--log-file` so the game writes no rotated default log, and captures stderr because that is
  where the leak records are. `--user-data-root` has the existing command-line-over-environment
  precedence and names a durable root. When neither source names one, the smoke creates a fresh
  private root, redirects `user://` and the log there, and removes the root after the result or
  failure envelope has been built. A successful result always reports the `engine_data_path`
  used; the ephemeral default's historical path is reported there, while `user_data_root` and
  `log_file` are omitted because they no longer exist. A caller-selected durable root reports
  all three placement fields. Failure envelopes do not publish placement unless ADR-0004 later
  admits those facts into `Failure evidence`.

### 3. Shared mechanics, command-owned policy

- Shared, reused and not copied: the launch primitive's streaming capture, its timeout with
  the `Failure evidence` clocks, the user-data placement and its disclosure, the bounded
  `stdout` projection, the shared recognizer, and the [Completion marker](../../CONTEXT.md)'s
  whole-line equality and silence window (ADR-0031). Genuinely generic failures stay shared:
  `launch_timeout`, and the launch-failure family of the `Raw run`.
- Owned by `script run` and untouched: its entry-script liveness (the marker arms on an error
  attributable to the ONE entry script) and its verdict codes `script_failed` /
  `script_aborted`, whose registry meaning stays the `script run` meaning.
- Owned by the smoke — its own policy with its own public codes, registered under ADR-0002:
  - `smoke_failed` (`operation`): under `--strict`, the run ended with a non-zero exit status
    OR a recognized exit-time leak — the evidence-backed rule from GDA-DF-072 and #844. Its
    `Failure evidence` reuses the existing shape: the child's `exit_status` and the parsed
    `script_errors`; `diagnostics` remains the separate human-readable prose.
  - `smoke_aborted` (`operation`): with a `--completion-marker` declared, the run was ended
    early because a recognized record that is not an exit-time process record appeared, the
    marker had not, and the run then went silent for the declared window. An exported game has
    no single entry script — the whole artifact is the entry — so this, not entry attribution,
    is the arming rule. Its evidence reuses `elapsed_seconds`,
    `termination_phase: aborted_on_error`, and the parsed `script_errors`.
  - Without `--strict`, a leak and a non-zero exit are data on the success result.
- The implementation slice updates ADR-0004's recorded producer set and its registry assertion
  for these two builders in the same change; it adds no `FailureEvidence` field.
- Rationale: the deep module is the launch; the two commands are two adapters with their own
  public semantics, so neither's codes are broadened as a shortcut for the other.

### 4. Declared on the command line only

No project-side declaration of the smoke's arguments or expectations (no `project.godot`
section, no gda config file). `export run --smoke` as composition sugar is possible later and
is not decided here.

### Left to the implementation slice and its review

The exact result key names for the artifact and executable observations; the exact messages of
the four codes; the executable's location rule per host; the per-host probes the slice records.
The placement and typed failure facts above are decided, including the required ADR-0004
producer-set update. Any PCK inspection (loader selection, header validity, the engine version
it carries, entry count) is NOT in this decision: it needs its own agent-value case and scope
before it is filed.

## Considered options

- **Reuse the `script run` contract verbatim (rejected, first review).** No `--arg`, an
  entry-script marker rule, and `script run`-described verdict codes.
- **Generalize `script_failed` / `script_aborted` to cover the smoke (rejected, second
  review).** A compatibility patch: the smoke arms its marker differently, so the codes would
  carry two meanings. The smoke owns `smoke_failed` / `smoke_aborted`.
- **An executable-plus-PCK identity on `export run`, then a bounded cross-platform inventory
  (both rejected, second review).** Each served a content-identity NFR with no evidence-backed
  need and hid platform differences (`output_path` is not an artifact-membership authority: the
  Web exporter writes siblings). Removed; the smoke reports only the caller's artifact path,
  the resolved executable and its explicitly bounded pre-launch digest. It does not report a
  PCK because discovery cannot establish loader choice.
- **A separate read-only `export verify` (rejected).** The same NFR under another name.
- **Additive smoke on `export run` (`--smoke`), rejected for now.** One result would carry a
  construction and a run, and a smoke must be re-runnable without exporting again.
- **A smoke-specific "clean" rule (any `ERROR:`/`WARNING:` line fails), rejected.** It would
  fail a release on an engine advisory unrelated to the project.
- **Reading the log file instead of stderr, rejected by measurement.** The leak records never
  reach it.
- **Running the artifact with the real `user://` by default, rejected.** A side effect on the
  developer's save directory; `--user-data-root` reaches it when a smoke needs it.
- **Verifying that the artifact came from the project, rejected.** gda has no fact to verify
  it against; the trust statement names two subjects instead.
- **The full artifact report (signing, metadata, architectures, source revision, receipt),
  rejected on #841.**

## Consequences

- This ADR is the current decision authority for #841; the issue keeps current acceptance
  criteria and links here, with its earlier requirement and decision text under a superseded
  block.
- CONTEXT.md gains `Export artifact` (named by the `output_path` `export run` reports, not by
  content) and `Artifact smoke`. The smoke is a separate caller-artifact execution point, not a
  point on the Project-code execution surface; its distinct trust subject is stated in §1.
- ONE implementation slice will be filed from this ADR (`/to-issues`, milestone #12, W5): the
  smoke, blocked by nothing but this ADR; serial with #839 on the export command module. No
  identity slice.
- Four codes enter the ADR-0002 registry: `export_artifact_not_found`,
  `export_artifact_not_runnable`, `smoke_failed`, `smoke_aborted`. The `script_*` codes are
  unchanged. The two smoke failure builders enter ADR-0004's existing evidence producer set.
- Artifact smoke is a sibling channel that uses the [Headless launch](../../CONTEXT.md)
  primitive with a different argv head; the slice reuses the primitive's streaming, timeout,
  placement and `Raw run` normalization rather than copying them.
- Not promised: content identity, provenance, a manifest, a sandbox, a network policy, signing
  interpretation, or non-desktop targets. A project's release portfolio stays the project's.
