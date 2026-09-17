---
status: accepted
---

# The artifact smoke runs a caller-selected Export artifact through the one-shot Godot headless launch

`gda export run` reports whether Godot constructed an [Export
artifact](../../CONTEXT.md). It does not run that artifact. In the kung-fu
dogfooding project, the first exported candidate loaded the whole game and then
reported four leaked WAV resources at exit, although `export run` had returned
`warnings: []` (GDA-DF-072). The defect was observable only by launching the
exported game.

The required capability is therefore small: run the caller-selected exported
game headlessly on the current host, bound the run, and return the process
evidence. Signing policy, release verification, artifact identity, provenance,
and attestation do not follow from that requirement.

The 2026-09-14 macOS probe used a Godot 4.6.3 release template exported through
`gda export run`. It established the facts this decision needs: the exported game
accepted `--headless` and `--log-file`; values after Godot's `--` separator reached
`OS.get_cmdline_user_args()`; stderr contained the exit-time leak records that the
log file omitted; and redirecting `HOME` redirected the game's `user://`. Linux and
Windows behavior was not measured, so the implementation must not claim more than
its own host probes establish.

A follow-up probe on 2026-09-15, on the same Godot 4.6.3 release template, found
one missing functional condition. With `--quit-after 30` before Godot's `--` separator, the
game exited normally and both leak records appeared on stderr. When an external
six-second bound sent `SIGTERM`, the game emitted no leak record. Passing the same
words after `--` made them user arguments and the game did not exit. Godot's 4.6.3
source [parses `--quit-after` outside the editor-only
guard](https://github.com/godotengine/godot/blob/4.6.3-stable/main/main.cpp#L1741-L1748)
and [ends the main loop after that many process
frames](https://github.com/godotengine/godot/blob/4.6.3-stable/main/main.cpp#L5056-L5062);
the normal engine shutdown then runs cleanup. A wall-clock termination cannot
provide equivalent shutdown evidence.

## Decision

gda adds one command:

```text
gda export smoke <artifact> [--arg VALUE ...] [--quit-after FRAMES] [--timeout SECONDS] [--strict]
```

The command is a separate caller-artifact execution point. It is not part of the
[Project-code execution surface](../../CONTEXT.md), because gda has no fact that
ties the caller-selected artifact to the resolved [Trusted
project](../../CONTEXT.md). It executes the artifact unsandboxed and makes no
provenance claim.

The command is projectless. Its `HeadlessCommand` descriptor sets
`inherits_project=False`, its CLI signature does not declare `--project`, and its
recipe neither resolves nor uses the invocation cwd or `GDA_PROJECT` as a project.
A relative filesystem `<artifact>` resolves against the invocation cwd. The
absolute `output_path` reported by `export run` therefore passes through directly.

### Product contract

- `<artifact>` is the path returned by `export run`, or another path selected by
  the caller.
- The first implementation accepts a directly runnable file on the current host.
  On macOS it also resolves the main executable of a `.app` bundle. An absent path
  is `export_artifact_not_found`; any present input that cannot be resolved to a
  host-runnable Godot executable is `export_artifact_not_runnable`. Both are
  classifier-source `operation` codes with process exit 4. The resolver does not
  classify export platforms or model inputs that it does not run.
- The executable is invoked with `--headless`, a gda-owned `--log-file`, and an
  optional `--quit-after FRAMES`, then Godot's `--` separator and every `--arg`
  value in order. `FRAMES` is a non-negative integer; omission or zero disables
  the engine-owned exit. There is no windowed mode in this capability.
- `--quit-after` asks Godot to end its main loop normally after the selected number
  of process frames, so engine cleanup and its exit-time diagnostics can run. The
  game can still exit earlier by itself. This is not a completion assertion and
  does not say that project-specific work finished.
- The existing `--timeout` and streaming capture remain the external wall-clock
  hard bound. A timeout is `launch_timeout`, preserves the output captured before
  termination, and makes no claim about diagnostics that Godot emits only during
  normal shutdown.
- A completed run returns the caller's artifact path, the resolved executable
  path, exit status, bounded stdout and its existing spill metadata, stderr, and
  recognized diagnostics. Exit status is data by default.
- `--strict` returns `smoke_failed` when the completed process has a non-zero exit
  status or the existing recognizer reports `shutdown_leak`. No other diagnostic
  becomes a release policy inside gda. `smoke_failed` is also a classifier-source
  `operation` code with process exit 4. Its builder carries the existing
  `FailureEvidence.exit_status` and `FailureEvidence.script_errors` values from the
  completed run; it adds no evidence field or command-specific envelope.
- The existing global `--user-data-root` and `GDA_USER_DATA_ROOT` override are
  honored. Without either, Artifact smoke creates a fresh private root after it
  resolves the artifact and before launch, so the exported game cannot mutate the
  user's real `user://`. It owns that root and attempts to remove it in `finally`
  for every outcome that created it, including launch and command failures,
  timeouts, and unexpected exceptions. Cleanup is best-effort internal hygiene:
  deletion failure does not replace the command outcome and adds no result field,
  error code, or `FailureEvidence`. An explicit override remains caller-owned.

There is no completion marker and no `smoke_aborted`. An exported game has no
single entry script whose continued output can serve the liveness contract that
ADR-0031 defines for `script run`. `--quit-after` is only Godot's normal-exit
mechanism; `--timeout` is still the external hard bound. Neither is a
project-specific completion protocol.

### Necessary shared abstraction

Artifact smoke integrates with the existing flow at the lowest stable seams:

1. **One-shot Godot headless launch.** Keep [Headless
   launch](../../CONTEXT.md) as the primitive for one Godot process in fixed
   headless mode. Its two executable sources are explicit: the configured editor
   executable used by existing Phase-1 channels, and the resolved executable of
   an Export artifact used by Artifact smoke. It continues to own process spawn,
   streaming capture, timeout, the gda-owned log, UTF-8 decoding, and normalized
   launch failures. It does not become a public or arbitrary-process runner.
2. **Explicit placement input.** Add only the narrow internal input needed for
   Artifact smoke to give Headless launch its fresh private root. Existing callers
   keep the current global placement resolution and behavior. The launch remains
   the single owner of preparing the placement and attaching its internal report.
3. **Completed passthrough result.** `script run` is no longer the only consumer
   of the completed process fields. Extract its existing exit-status, bounded
   stdout and spill metadata, stderr, and diagnostics into one shared result base;
   `script run` adds its script path and existing placement fields, while Artifact
   smoke adds only artifact and executable paths. Generalize the existing stdout
   spill implementation and `stdout_spill_failed` wording only as far as these two
   concrete consumers require.
4. **Public self-description.** Add `ExecutionKind.ARTIFACT_SMOKE` so `--schema`
   describes this execution shape accurately. As with `SCRIPT_RUN`, the kind is
   metadata; it adds no runner registry or dispatch strategy.

This is the necessary abstraction between two demonstrated consumers. Copying
the launch or completed-result logic would restart symptom-patch accumulation;
generalizing it beyond one-shot Godot headless execution would create an
NFR-driven process platform that the requirement does not justify.

### Command-owned policy

The Headless launch reports mechanism outcomes. Artifact smoke owns the two input
refusals and `smoke_failed`. `script run` keeps its entry-script validation,
completion-marker policy, placement fields, and `script_failed` /
`script_aborted` meanings unchanged. Project-specific release checks remain with
the caller: multiple completion markers, warning bans, signing checks, soak time,
network policy, and combinations of those checks are policies over the returned
evidence, not additions to this command. The smoke's direct `--quit-after` mapping
does not interpret any of them.

### Validation required by the implementation slice

- Feed the `output_path` from a real `export run` result to `export smoke`.
- Prove that ordered `--arg` values reach the exported game after Godot's `--`.
- Prove that omitted or zero `--quit-after` adds no engine exit, while a positive
  value appears before `--`, ends the release template normally, and exposes its
  exit-time diagnostics.
- Prove that a normal non-zero exit is returned as data, while `--strict` maps a
  non-zero exit or `shutdown_leak` to `smoke_failed`, with the existing typed exit
  status and script-error evidence.
- Prove that a timeout preserves partial stdout and stderr but does not claim a
  normal cleanup or the absence of shutdown-only diagnostics.
- Prove that an invocation outside a Godot project ignores inherited project
  context, that the command rejects `--project`, and that relative filesystem
  artifact paths resolve against the invocation cwd.
- Prove that the default private `user://` does not touch the real user directory;
  cleanup is attempted after completed, timeout, launch-failure, strict-failure,
  and unexpected-exception paths; a simulated deletion failure does not replace
  the outcome; and the existing explicit global override still works and is not
  removed.
- Keep every existing Headless launch caller behavior unchanged.
- Keep CLI help, per-command schema, aggregate schema, and MCP discovery
  consistent with the new command and `ExecutionKind`.
- Update ADR-0004's `FailureEvidence` producer-set authority, the descriptions of
  the two reused fields, and its registry guard tests when the `smoke_failed`
  builder is implemented.
- Assert through public help, schema, and result regression tests that the removed
  digest/PCK/inventory, windowed-mode, completion-marker, transient-placement, and
  `smoke_aborted` surfaces do not return. Keep the generic-runner and ownership
  exclusions as architecture-review boundaries; add a focused test only where an
  observable public seam exists.

## Causal correction

PR #978 did not converge because each review repaired the latest contradiction
without resetting the contract that produced it:

1. The dogfooding note combined the functional need to run an exported game with
   a release-verification portfolio. The first design therefore coupled Artifact
   smoke to executable/PCK identity and changes to `export run`.
2. A Web-export counterexample disproved that identity model. The response widened
   it into a bounded cross-platform inventory instead of asking whether content
   identity was required. The NFR became a platform abstraction while still
   failing to establish identity.
3. Removing the inventory left the copied `script run` contract in place.
   Script-specific error codes were first generalized and then replaced with
   smoke-specific codes, but completion-marker semantics survived even though an
   artifact has no single entry script.
4. Reusing the whole launch facade then broadened Headless launch to arbitrary
   binaries and headless/windowed modes. Digest caveats, placement disclosure,
   cleanup rules, and failure-evidence rules accumulated to defend commitments
   that were not part of the user outcome.
5. The first-principles reset removed those mechanisms but overcorrected once: it
   assumed the exported game would exit by itself and called timeout the only
   supported end condition. The representative defect appears during normal
   engine cleanup, while timeout termination does not run that path. Direct
   release-template evidence restored the existing engine flag without restoring
   a project protocol or platform abstraction.

The root cause was reuse at public-contract boundaries instead of at the lowest
stable mechanism. Small technical possibilities were promoted into product
obligations, and project release policy was mixed into a gda capability. The
recovery is subtraction: retain the functional run, extract only sharing proven by
the second consumer, and delete the compensating contract around unneeded NFRs.

## Considered options

- **Reuse `script run` verbatim — rejected.** Its entry-script validation and
  completion marker are not properties of an exported game.
- **Require every exported game to implement its own exit protocol — rejected.**
  It would move a Godot engine capability into every project and would not exercise
  the normal exit path by default. The optional engine `--quit-after` flag is the
  smaller mechanism; callers still own any assertion that project work completed.
- **Restore Headless launch to editor-only — rejected.** The exported game is
  still a Godot executable and needs the same one-shot headless mechanics. An
  editor-only definition would misdescribe the real shared abstraction.
- **Generalize Headless launch into an arbitrary process or mode platform —
  rejected.** No current requirement needs arbitrary executables, windowed mode,
  a runner registry, or platform strategies.
- **Add artifact digests, PCK discovery, an inventory, provenance, or a receipt —
  rejected.** These are content-identity or audit NFRs without evidence-backed
  need in #841. A digest observation with a non-atomic caveat is still residue of
  that invalid requirement.
- **Add `export run --smoke` — rejected for now.** Export construction and
  re-runnable observation are separate operations. Composition can remain with
  the caller until evidence supports product syntax.
- **Encode the kung-fu release portfolio — rejected.** Its several markers,
  warnings policy, signing checks, and other gates remain project-owned.

## Consequences

- #841 and this ADR define one bounded headless run, not a release-verification
  platform.
- The implementation adds three classifier-source `operation` codes with process
  exit 4:
  `export_artifact_not_found`, `export_artifact_not_runnable`, and
  `smoke_failed`. The strict failure reuses `FailureEvidence.exit_status` and
  `FailureEvidence.script_errors`; the implementation updates ADR-0004's producer
  set, field descriptions, and guard tests. It adds no `smoke_aborted` and no new
  `FailureEvidence` shape.
- `--quit-after` maps one optional non-negative value to Godot's existing engine
  flag before `--`. It adds no result field, error code, marker protocol, or
  termination abstraction.
- `CONTEXT.md` defines Headless launch by its stable Godot/headless semantics and
  names the two known executable sources. Existing Phase-1 callers retain their
  current behavior.
- The implementation may share the completed-result base and the explicit
  placement input only. It must not introduce artifact identity, a generic
  process platform, a platform-format taxonomy, project configuration, or release
  policy.

> **Outcome (2026-09-17, #979 / PR #987):** the shared "completed passthrough
> result" is a base that carries the RULE and declares NO fields — the stdout cap,
> the bounded projection and its spill IO, the published truth table, the runtime
> validator, the default ceiling and the human rendering tail — because pydantic
> orders a subclass's fields base-first, so a field-carrying base would have moved
> `script run`'s `path` out of first position and broken the byte-identical result
> and output-schema shape this decision's own validation list requires; each result
> therefore declares its own fields, which is the precedent `gda.models
> .ProjectRootedResult` set for the same reason. It lives in a new
> `gda.completed_run` rather than in the `gda.models` core because it owns
> behaviour, not only a shape (see ADR-0040's note of the same date). Artifact
> resolution shipped as declared and no wider: a regular file the host may execute
> is accepted as given, a `.app` bundle resolves through
> `Contents/Info.plist`'s `CFBundleExecutable` to `Contents/MacOS/<that name>`
> which must itself be a regular file the host may execute, and every other
> shape — any other directory, a bundle missing that plist, key or file, a file
> without execute permission — is `export_artifact_not_runnable`; the bundle rule
> is NOT gated on the host platform, because it reads a layout the artifact
> declares and gating it would be the platform classification this decision
> rejects. The two `main/main.cpp` links in the context above were corrected in
> place as a citation erratum — `--quit-after` is parsed at L1741-L1748 and ends
> the main loop at L5056-L5062 at 4.6.3-stable — leaving the sentences around them
> unchanged.
