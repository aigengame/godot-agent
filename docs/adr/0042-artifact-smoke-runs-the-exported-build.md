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
`gda export run`, 2026-09-14; reproducible from the probe described on #841):**

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

**gda gains ONE new point on the [Project-code execution surface](../../CONTEXT.md): the
[Artifact smoke](../../CONTEXT.md), `gda export smoke <artifact>`, which runs a same-host
desktop exported game.** It is the release-stage leg of the agent's write → run → observe →
fix loop. ADR-0025 holds on both criteria: agent value (the defect above was observable
nowhere else) and structured-operation fit (a bounded one-shot run, one `--json` result, a
`--schema`, the existing `GdaError` envelopes).

### 1. Two trust subjects, stated once

- The resolved [Trusted project](../../CONTEXT.md) (ADR-0009) is the subject of every other
  point on the surface.
- The caller-selected Export artifact is a DISTINCT subject: gda executes it unsandboxed, with
  no verified provenance — gda has no fact to tie the artifact to the project and does not
  claim one. The relation is the one gda already has with `--project`: the caller chooses what
  gda runs.
- This sentence is the only statement of that trust; CONTEXT.md's surface entry refers to it
  and does not fold the smoke into "no new trust axis".

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
  (#850), and the LAUNCH TARGET the smoke used: the executable's path and SHA-256, and the path
  and SHA-256 of a separate `.pck` found beside it when there is one. The launch target is an
  observation of what ran — it lets a reader tell which of several candidates a verdict
  belongs to (GDA-DF-072 had three) — and is not an identity, a manifest or a provenance of
  the artifact.
- Headless by default, `--windowed` opt-in (the `daemon start` precedent). `user://` goes to a
  fresh private root per run by default; `--user-data-root` names a durable one. gda passes
  `--log-file` so the game writes no rotated default log, and captures stderr because that is
  where the leak records are.

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
    OR a recognized exit-time leak — the evidence-backed rule from GDA-DF-072 and #844; the
    envelope carries the diagnostics as `Failure evidence`.
  - `smoke_aborted` (`operation`): with a `--completion-marker` declared, the run was ended
    early because a recognized record that is not an exit-time process record appeared, the
    marker had not, and the run then went silent for the declared window. An exported game has
    no single entry script — the whole artifact is the entry — so this, not entry attribution,
    is the arming rule.
  - Without `--strict`, a leak and a non-zero exit are data on the success result.
- Rationale: the deep module is the launch; the two commands are two adapters with their own
  public semantics, so neither's codes are broadened as a shortcut for the other.

### 4. Declared on the command line only

No project-side declaration of the smoke's arguments or expectations (no `project.godot`
section, no gda config file). `export run --smoke` as composition sugar is possible later and
is not decided here.

### Left to the implementation slice and its review

The result's field-level shape; the exact messages of the four codes; the executable's location
rule per host; the per-host probes the slice records. Any PCK inspection (header validity, the
engine version it carries, entry count) is NOT in this decision: it needs its own agent-value
case and scope before it is filed.

## Considered options

- **Reuse the `script run` contract verbatim (rejected, first review).** No `--arg`, an
  entry-script marker rule, and `script run`-described verdict codes.
- **Generalize `script_failed` / `script_aborted` to cover the smoke (rejected, second
  review).** A compatibility patch: the smoke arms its marker differently, so the codes would
  carry two meanings. The smoke owns `smoke_failed` / `smoke_aborted`.
- **An executable-plus-PCK identity on `export run`, then a bounded cross-platform inventory
  (both rejected, second review).** Each served a content-identity NFR with no evidence-backed
  need and hid platform differences (`output_path` is not an artifact-membership authority: the
  Web exporter writes siblings). Removed; the smoke reports only the launch target it used.
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
  content) and `Artifact smoke`, and its `Project-code execution surface` entry names the smoke
  as its widest point — the game's startup path and whatever code the run reaches within the
  caller's bound, never every script the PCK carries — with the distinct trust subject stated
  by reference to §1.
- ONE implementation slice will be filed from this ADR (`/to-issues`, milestone #12, W5): the
  smoke, blocked by nothing but this ADR; serial with #839 on the export command module. No
  identity slice.
- Four codes enter the ADR-0002 registry: `export_artifact_not_found`,
  `export_artifact_not_runnable`, `smoke_failed`, `smoke_aborted`. The `script_*` codes are
  unchanged.
- The launch is a sibling of the [Headless launch](../../CONTEXT.md) primitive with a different
  argv head; the slice reuses the primitive's streaming, timeout, placement and `Raw run`
  normalization rather than copying them.
- Not promised: content identity, provenance, a manifest, a sandbox, a network policy, signing
  interpretation, or non-desktop targets. A project's release portfolio stays the project's.
