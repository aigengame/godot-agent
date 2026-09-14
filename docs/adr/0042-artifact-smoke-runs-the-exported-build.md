---
status: accepted
---

# The artifact smoke: `gda export smoke` runs the exported game, on the `script run` mechanics with its own policy

Every piece of evidence gda produces today runs the PROJECT under the editor binary: a
[Headless operation](../../CONTEXT.md), `gda script run` (ADR-0031), `gda scene preflight`
(#664), and a [Live operation](../../CONTEXT.md) inside an [Engine session](../../CONTEXT.md).
Nothing observes the [Export artifact](../../CONTEXT.md). `gda export run` constructs one and
reports the construction — preset, platform, mode, output path, the directories it created,
the engine's warnings — and that result was read as "releasable" on three candidates of the
kung-fu dogfooding project (GDA-DF-072, gda 0.11.0). The first candidate loaded the whole game
and leaked four WAV resources at exit. That defect was observable only by running the exported
game, which the export's `warnings: []` could not see. An exported game differs from the
project the editor binary runs: it uses the release template, its PCK holds what the export
filters admitted, the harness is stripped (ADR-0028), and imported resources are remapped.
Issue #841 asked for two capabilities — an artifact report and a declared post-export smoke —
and required a scope decision before either was built.

**Narrowed first (2026-09-14, recorded on #841 as "Scope decision, part 1").** Signing
observations, bundle metadata, the architecture list, the exported project's source revision,
a deny-network launch and the "receipt / attestation" framing are OUT. An agent can call
`codesign`, `plutil` and `lipo` itself, so wrapping them adds no agent value (ADR-0025
criterion 1). Whether a signature is valid is the project's release policy, not a fact gda
interprets. Reading git would be a new dependency and a new precedent, while the artifact
hashes already are the identity. Auditability is a non-functional requirement that needs its
own case. These items entered from one macOS notarization workflow — a small situation, not a
product promise.

**Measured before deciding (Godot 4.6.3 release template, macOS universal, unsigned probe
exported through `gda export run`, 2026-09-14; reproducible from the probe described on
#841):**

- The exported game accepts `--headless` and `--log-file`. It exits with the script's own
  `quit(N)`. A windowed run works too.
- The release template still prints `push_error`, `push_warning` and BOTH exit-time leak
  records (`ObjectDB instances leaked at exit`, `N resources still in use at exit`). The leak
  records reach stderr only. The `--log-file` file never holds them, because the file logger
  closes before the leak detection runs.
- Arguments after Godot's `--` separator reach `OS.get_cmdline_user_args()` and never
  `OS.get_cmdline_args()`. Arguments before it are not refused by an exported game; they land
  in `OS.get_cmdline_args()` beside the engine's own.
- Setting `HOME` (the macOS lever of the [User-data placement](../../CONTEXT.md)) redirects
  the exported game's `user://` exactly as it does the editor binary's. The real user directory
  stays untouched.
- The PCK is a separate `Contents/Resources/<name>.pck` unless the preset embeds it.

Not measured: Linux, Windows and Web artifacts. The first implementation slice pins what it
promises on each platform with its own probes.

## Decision

**gda gains ONE new point on the [Project-code execution surface](../../CONTEXT.md): the
[Artifact smoke](../../CONTEXT.md), `gda export smoke <artifact>`, which runs the exported
game.** It is the release-stage leg of the agent's write → run → observe → fix loop and the
only observation of the exported game. The ADR-0025 test holds on both criteria: agent value
(the defect above was observable nowhere else) and structured-operation fit (a bounded
one-shot run with one `--json` result, a `--schema`, and the existing `GdaError` envelopes —
the shape `script run` already publishes).

### 1. Trust: the caller-named artifact is executed unsandboxed

- Requirement: the smoke runs the artifact the caller names, which may be any existing path.
- Mechanism: gda executes that artifact's own executable directly. No sandbox, no network
  policy, no signature check.
- Policy: the [Trusted project](../../CONTEXT.md) assumption (ADR-0009) is EXTENDED to the
  artifact the caller names. gda does not verify that the artifact came from the resolved
  project; the association is the caller's. The identity the smoke echoes (below) lets the
  caller check the launched bytes against the identity `export run` reported.
- Rationale: the relation is the one gda already has with `--project` — the caller chooses
  what gda runs. Stated plainly rather than argued away: an echoed hash proves which bytes ran,
  not where they came from.

### 2. Identity lives where the artifact is born, and is echoed where it is run

- Requirement: a construction result and a smoke result must correlate by content, on every
  platform `export run` produces (macOS bundle; Linux and Windows executable with a separate or
  embedded PCK; a Web directory; Android and iOS outputs; a bare PCK in `pack` mode).
- Mechanism: `export run` reports, as additive fields, a bounded INVENTORY of the files under
  the output path — path relative to the output, size, SHA-256; a fixed entry cap and a
  `truncated` flag — plus the PCK facts for the PCK found among them: header validity, the
  engine version the header carries, entry count, and whether it is embedded. A separate PCK
  is inventoried as a file with its own digest. An embedded PCK has no digest of its own: the
  executable's digest covers it, the header is read at the offset the embedded trailer names,
  and the result says `embedded: true`. The gda provenance `gda --version --json` already
  computes rides along. `pack` mode inventories its bare PCK. The smoke echoes the same
  identity for the artifact it launched.
- Failure policy: an identity fact gda cannot read (an unparsable PCK header, an unreadable
  file) is null with a reason field. It never fails the parent result and is never fabricated.
  `export run`'s `warnings` keeps its engine-advisory meaning (#839's rule).
- Rationale: the inventory is platform-agnostic, so S1 needs no per-platform model; the PCK
  half is engine knowledge an agent cannot get from `shasum`. There is no `export verify`
  command: a read-only re-check of an existing artifact is a narrow case.

### 3. Shape: the `script run` MECHANICS, with smoke-specific POLICY

- Requirement: one operation, one result (ADR-0004), under the `export` group because the
  artifact is the export domain object (ADR-0005). The smoke must be re-runnable on an artifact
  exported earlier, without exporting again.
- Mechanics reused, not copied: the launch primitive's streaming capture, its timeout with the
  `Failure evidence` clocks, the [User-data placement](../../CONTEXT.md) and its disclosure
  (#850), the bounded `stdout` projection (#665), the shared recognizer over stderr, and the
  [Completion marker](../../CONTEXT.md)'s whole-line equality and silence window (ADR-0031).
- Policy the smoke states for itself:
  - The positional is the `output_path` `export run` reported. Parameters: repeatable `--arg`,
    `--timeout`, `--completion-marker`, `--strict`, `--windowed`, `--user-data-root`.
  - The argv is the artifact's executable, `--headless` unless `--windowed`, `--log-file` on a
    gda-owned path, then `--`, then every `--arg` value in order. Caller arguments therefore
    reach `OS.get_cmdline_user_args()` and can never be read as engine options.
  - The result carries `exit_status`, the bounded `stdout`, `stderr` verbatim, `diagnostics`,
    the placement, and the identity echo. The run ending is success; the exit status is data.
  - The marker's arming condition: `script run` arms its watch on an error attributable to the
    one entry script. An exported game has no single entry script — the whole artifact is the
    entry — so the smoke arms on ANY recognized record that is not an exit-time process record.
    The marker still ends the run only after the declared silence window, as in ADR-0031.
  - `--strict` fails on a non-zero exit OR a recognized exit-time leak: the `script run`
    predicate, through #976's policy table once it lands. No derived `clean` boolean. A project
    `push_warning` is not in the recognizer's closed set; a project that rejects every warning
    applies that policy over the verbatim `stderr` itself.
  - Headless by default, `--windowed` opt-in (the `daemon start` precedent). `user://` goes to
    a fresh private root per run by default; `--user-data-root` names a durable one. gda passes
    `--log-file` so the game writes no rotated default log, and captures stderr because that is
    where the leak records are.
- Rationale: the caller learns one run contract; the two things that genuinely differ (the
  entry identity and the argument placement) are stated instead of inherited.

### 4. Failure semantics and the error-code registry

- Refusals before launch, two new `operation` codes registered under ADR-0002:
  `export_artifact_not_found` (the path is absent) and `export_artifact_not_runnable` (the
  host cannot run it: a `pack`-mode bare PCK, a bundle with no executable, a Web, Android or
  iOS artifact, an executable for another platform).
- Runnable matrix: a macOS bundle on a macOS host, a Linux executable on a Linux host, a
  Windows executable on a Windows host. Nothing else. The refusal names the platform it saw.
- Launch failures: the classifiers `script run` uses — `launch_timeout` with its evidence
  clocks, and the early end the marker declares.
- Verdict codes: `script_failed` and `script_aborted` are GENERALIZED, not duplicated. Their
  registry descriptions (pinned under ADR-0002) will say "a passthrough run — `script run`, or
  an artifact smoke" and keep their meaning: the run ended by the caller's declared contract.
  Two smoke-specific codes were rejected: the verdicts are the same contract, and an agent
  branching on them would learn one vocabulary.
- The game's own exit status is data unless `--strict`.

### 5. Declared on the command line only

No project-side declaration of the smoke's arguments or expectations (no `project.godot`
section, no gda config file). `export run --smoke` as composition sugar is possible later and
is not decided here.

### Left to the implementation slices and their reviews

The field-level shape of the inventory and the reason field; the inventory cap; the PCK header
reader and the embedded-trailer offset; the exact messages of the two codes; the executable's
location per platform (a macOS bundle's `Contents/MacOS/<name>`, a bare executable elsewhere);
the per-platform probes S1 records for what it promises.

## Considered options

- **Reuse the `script run` contract verbatim (rejected in review).** `script run` has no
  `--arg`, arms its marker on the one entry script, and its verdict codes are described as
  `script run` semantics. Mechanics are reused; the policy that differs is stated above.
- **Additive smoke on `export run` (`--smoke`), rejected for now.** One result would carry a
  construction and a run; GDA-DF-072 asked for exactly the opposite distinction, and a smoke
  must be re-runnable on an artifact exported earlier.
- **A separate read-only `export verify` for the identity facts, rejected.** A third command
  for a narrow case; most of its facts an agent gets from `shasum`.
- **A per-platform identity model (executable + PCK only), rejected in review.** It covered
  desktop outputs only; the bounded inventory covers every platform `export run` produces.
- **A smoke-specific "clean" rule (any `ERROR:`/`WARNING:` line fails), rejected.** It would
  fail a release on an engine advisory unrelated to the project and give the agent a second
  verdict vocabulary.
- **Two smoke-specific verdict codes, rejected.** Same contract, one vocabulary; the registry
  descriptions are generalized instead.
- **Reading the log file instead of stderr, rejected by measurement.** The leak records never
  reach it.
- **Running the artifact with the real `user://`, rejected as the default.** A smoke that
  writes into the developer's save directory is a side effect; `--user-data-root` reaches the
  real one when a smoke needs it.
- **Verifying that the artifact came from the project, rejected.** gda has no fact to verify
  it against; the trust statement is extended instead.
- **The full artifact report (signing, metadata, architectures, source revision), rejected.**
  The part-1 narrowing above.

## Consequences

- CONTEXT.md gains two terms in the same change — `Export artifact` and `Artifact smoke` — and
  its `Project-code execution surface` entry names the smoke as its widest point: the exported
  game's startup path (autoloads and the main scene) and whatever code that run reaches within
  the caller's bound. It does not run every script the PCK carries, and no text may claim so.
- Two follow-up slices will be filed from this ADR (`/to-issues`, milestone #12, W5): **S1**
  the identity fields on `export run`, **S2** `export smoke`. S2 is blocked by S1 (the echo);
  both are serial with #839 on the export command module.
- The `script_failed` and `script_aborted` registry descriptions are amended by S2 under
  ADR-0002's description pin.
- The launch is a sibling of the [Headless launch](../../CONTEXT.md) primitive with a different
  argv head; S2 reuses the primitive's streaming, timeout, placement and `Raw run`
  normalization rather than copying them.
- The recognizer (`gda.script_errors`) gains a consumer that is not an editor-binary run. Its
  closed set and admission rule are unchanged; the release template prints the same records.
- Not promised: the smoke does not sandbox the game, does not deny it the network, and does not
  interpret signing. A project's release portfolio stays the project's.
