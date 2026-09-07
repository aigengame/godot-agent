# Selected execution dependency closure

Status: implementation in progress for [#874](https://github.com/aigengame/godot-agent/issues/874).
This record refines bADR-0028 decision 3 and PLAN claim C3. It does not close #874,
the mandatory deletion in #875, or the parent. The source baseline is
`3b661f85cf8a3d1acec84c4e0482a5c59e0a0cf4`.

## Decision and observed defect

Keep RIR as the sole public executable representation. Close its actual rules,
refusal definitions and resource laws, then pass an immutable admitted request to
execution and independent result validation. Select input and output contracts at
their existing boundaries. Keep exact producer provenance downstream of executable
meaning. This is a continuation of the accepted deletion design under the owner's
delegation in [IMPLEMENTATION.md](IMPLEMENTATION.md).

A legal baseline experiment demonstrates the omission. Starting from the maintained
`structured-selection` Model, enlarge its admitted SelectionState list bounds and
authored lists to 64 members. Independently seal and admit three authorities with
`max_rule_match_steps` of 837, 838 and 839, updating their resource-boundary vectors.
All three normal Model builds produce eight artifacts and exactly the same RIR:

- Semantic identity: `sha256:dd8a5e1400ba5d918cf73ae88f4d941df943cc64fd9245e67daaf7a53f58cfbb`.
- Content identity: `sha256:27640bf06e9285ef3f866f815a6a93a8d312e48b23393df4d09bbfa53e1a69ef`.
- At 837, Experiment assignment admission returns the complete typed
  `language.structured_value_resource_exhausted` refusal before dispatch.
- At 838 and 839, the real Runtime completes selection and observation; independent
  artifact-set validation succeeds. Runtime lookup and independent replay each
  consume 838 structured-value steps.

This is a Domain build/check/run witness, not a CLI/HTTP or authenticated Replay
pass. It does not establish an unhandled Runtime exception. Permanent public-path
tests must preserve these distinctions and make the missing identity dependency
fail on the baseline before passing on the implementation.

A separate caller-mutation probe did not find an input alias defect:
`check_experiment_value` already canonicalizes and parses the caller's JSON.
Changing that original seed leaves the checked request and two complete Runtime
artifact sets unchanged; a new check sees the new seed. This is preserved behavior,
not a baseline failure attributed to the new immutable contract view.

## Ownership and identity boundaries

| Input | Existing owner and selected representation | Required observation |
| --- | --- | --- |
| Program, nominal Types, Operations, Formula bodies and calls | Model's final specialized RIR and recursive owned closure | Missing, ambiguous, wrong-owner or incoherent closure refuses; actual semantic changes alter RIR meaning. |
| Node signatures, charges, numeric/RNG/scheduler/transaction/value laws, implicit and authored refusals | Kernel/LDB definitions selected into RIR after final specialization | Every consumed law has an explicit dependency, including initialization, nested guards, observation and terminal refusal. |
| Structured-value rule budget | Existing LDB resource, explicitly projected into RIR execution resources | The 837/838/839 witness has distinct semantic identities; no ambient resource lookup supplies a missing value. |
| Seed, streams, assignment, external input, Event order and terminal/metric policy | Admitted Experiment intent | The appropriate execution identity changes or admission refuses when meaning changes. |
| Input/import/result decoding and exact artifact construction | Existing Artifact Contract and Wire Schema owners, selected for the requested kinds | Exact contract mismatch or coherent tampering refuses. Schema descriptions and unrelated formats do not become numeric program meaning. |
| Replay comparison policy | Comparison's selected owned policy | Wrong or unsupported policy refuses; changing a comparator does not rewrite an ordinary run's program identity. |
| Producer and publication details | Build, evaluator and Publication receipts | Exact bytes and producer records remain truthful. Their unnecessary eligibility bindings must be deleted in #875. |

The identity order is definitions and laws → selected program → authored execution
intent → observations and exact receipts. A program identity must not depend on a
downstream receipt, its own identity field, the complete language inventory, or a
compiler label. A schema is admitted authority data; accepting an artifact-supplied
schema because it validates that artifact is not independent semantic admission.

For #874's mutation AC, operative execution laws change selected program/execution
meaning or refuse. Input and decoding laws must be selected, identified and checked
at their own boundaries: a changed exact contract must not silently reinterpret old
bytes. This does not require a schema description to alter arithmetic or RNG identity.

## Implementation and acceptance

1. Extend the existing machine-owned RIR selection and admission rules with the
   missing law, resource and owned reason/diagnostic dependencies. Select the final
   specialized instruction graph, including initialization and observation Formula
   programs. Preserve independent imported-program validation and the single
   request preparation delivered by #873.
2. Make CheckedExperiment retain a detached immutable intent/program/contract
   snapshot. Runtime, structured-value admission, scheduler and independent artifact
   replay consume that snapshot without a full-LDB fallback. Preserve independent
   interpreters, atomic Event refusal and truthful terminal audit.
3. Deepen the existing artifact owner so execution can construct and verify through
   one selected contract. Keep one canonical serializer and validation implementation.
   Publication authenticates exact sets and transaction anchors; Comparison owns
   Replay eligibility. Protocol descriptions and ingress limits remain at their
   respective CLI/HTTP boundaries.
4. Execute the dependency mutation matrix and actual CLI/HTTP build/run/Replay and
   session cases. Include recursive nominal ownership, selected/unselected rules,
   all consumed budgets, implicit refusal, initialization, rollback, terminal audit,
   nested input/output mutation and stale handles. Test counts alone cannot close
   these clauses.
5. Independently review Standards, Spec and domain architecture at the fixed PR
   head, resolve findings, and pass the required package/source/wheel/public checks.
   #874 remains open until all its own AC are evidenced.

The current whole-LDB/Build/compiler gates, broad evaluator fingerprint, full
reproduction equality, current CLI descriptor equality and transitive provenance
in observation identities are explicitly transitional. #875 must remove their
obsolete fields, propagation, validators and fallback routes across execution,
Replay and sessions. A new selected digest beside those old mechanisms is not the
endpoint. Coherent rollback restores code, machine authority, authored sources and
current evidence together to the preceding reviewed development revision.

The first boundary implementation selects exact output contracts from the existing
success/verdict/runtime-refusal member sets, uses those snapshots for construction
and verification, and freezes the admitted request's nested data. Its 54 selected
checks cover Model preparation, initialization refusal, Event rollback, independent
artifact replay, HTTP sessions and an actual built-wheel service. The wheel check
first failed because the default uv cache was not writable; it passed with a
task-local cache. Ruff and focused Pyright also pass. These results validate the
boundary foundation only; the RIR closure, full mutation matrix, final independent
reviews and required CI remain incomplete.

## Alternatives and external checks

An Experiment-only closed payload could avoid changing RIR immediately, but would
leave the public program identity incomplete and require every consumer to derive
another semantic payload. The selected design extends the established owner and
keeps the extra contract view private. Retaining current full-LDB lookups, even with
an additional digest, fails the accepted closure and deletion requirements. A whole
Kernel copy, all-schema digest, general dependency DSL, global registry or source
filename allowlist adds mechanisms without proving the required boundary.

The [Remote Execution API at commit 77ec630](https://github.com/bazelbuild/remote-apis/blob/77ec630134abbf9aa525f921eee4e5d11dc20f7e/build/bazel/remote/execution/v2/remote_execution.proto#L608)
binds the command, recursive inputs and execution timeout before execution, while
recording execution metadata downstream. Its timeout rationale corroborates the
need to identify a behavior-changing budget. Its operational defaults and salt do
not prove minimal semantic closure. No RPC, CAS or cache system is adopted.

The [Nix 2.35.2 derivation manual](https://nix.dev/manual/nix/2.35/store/derivation/index.html#inputs)
assigns responsibility for collecting every required input to the derivation creator.
It supports explicit dependency construction, not historical language retention or
adoption of a Nix store. [SLSA v1.2 provenance](https://slsa.dev/spec/v1.2/build-provenance#builddefinition)
separates input descriptions from run details and explicitly limits dependency
completeness guarantees. A provenance digest alone therefore cannot establish the
local closure claim. These sources are design provenance; machine authority and
permanent local counterexamples own this implementation's meaning and evidence.
