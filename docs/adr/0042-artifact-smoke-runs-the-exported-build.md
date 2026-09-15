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

## Decision

gda adds one command:

```text
gda export smoke <artifact> [--arg VALUE ...] [--timeout SECONDS] [--strict]
```

The command is a separate caller-artifact execution point. It is not part of the
[Project-code execution surface](../../CONTEXT.md), because gda has no fact that
ties the caller-selected artifact to the resolved [Trusted
project](../../CONTEXT.md). It executes the artifact unsandboxed and makes no
provenance claim.

### Product contract

- `<artifact>` is the path returned by `export run`, or another path selected by
  the caller.
- The first implementation accepts a directly runnable file on the current host.
  On macOS it also resolves the main executable of a `.app` bundle. An absent path
  is `export_artifact_not_found`; any present input that cannot be resolved to a
  host-runnable Godot executable is `export_artifact_not_runnable`. The resolver
  does not classify every export platform or model formats that it does not run.
- The executable is invoked with `--headless`, a gda-owned `--log-file`, then
  Godot's `--` separator and every `--arg` value in order. There is no windowed
  mode in this capability.
- The run uses the existing timeout and streaming capture. A timeout remains the
  existing `launch_timeout` and preserves the output captured before termination.
- A completed run returns the caller's artifact path, the resolved executable
  path, exit status, bounded stdout and its existing spill metadata, stderr, and
  recognized diagnostics. Exit status is data by default.
- `--strict` returns `smoke_failed` when the completed process has a non-zero exit
  status or the existing recognizer reports `shutdown_leak`. No other diagnostic
  becomes a release policy inside gda.
- The existing global `--user-data-root` and `GDA_USER_DATA_ROOT` override are
  honored. Without either, Artifact smoke uses a fresh private root so the
  exported game cannot mutate the user's real `user://`; gda removes that root on
  completion. The temporary placement is an internal safety mechanism, not a
  result field or a durable product artifact.

There is no completion marker and no `smoke_aborted`. An exported game has no
single entry script whose continued output can serve the liveness contract that
ADR-0031 defines for `script run`. The bounded timeout is the only generic end
condition that the requirement supports.

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
evidence, not additions to this command.

### Validation required by the implementation slice

- Feed the `output_path` from a real `export run` result to `export smoke`.
- Prove that ordered `--arg` values reach the exported game and that the game can
  exit by itself.
- Prove that a normal non-zero exit is returned as data, while `--strict` maps a
  non-zero exit or `shutdown_leak` to `smoke_failed`.
- Prove that a timeout preserves partial stdout and stderr.
- Prove that the default private `user://` does not touch the real user directory
  and is removed, and that the existing explicit global override still works.
- Keep every existing Headless launch caller behavior unchanged.
- Keep CLI help, per-command schema, aggregate schema, and MCP discovery
  consistent with the new command and `ExecutionKind`.
- Assert that the result and schema contain no digest, PCK discovery, identity,
  completion marker, windowed mode, transient placement field, or platform-model
  object.

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

The root cause was reuse at public-contract boundaries instead of at the lowest
stable mechanism. Small technical possibilities were promoted into product
obligations, and project release policy was mixed into a gda capability. The
recovery is subtraction: retain the functional run, extract only sharing proven by
the second consumer, and delete the compensating contract around unneeded NFRs.

## Considered options

- **Reuse `script run` verbatim — rejected.** Its entry-script validation and
  completion marker are not properties of an exported game.
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
- The implementation adds three operation codes:
  `export_artifact_not_found`, `export_artifact_not_runnable`, and
  `smoke_failed`. It adds no `smoke_aborted` and no new `FailureEvidence` shape.
- `CONTEXT.md` defines Headless launch by its stable Godot/headless semantics and
  names the two known executable sources. Existing Phase-1 callers retain their
  current behavior.
- The implementation may share the completed-result base and the explicit
  placement input only. It must not introduce artifact identity, a generic
  process platform, a platform-format taxonomy, project configuration, or release
  policy.
