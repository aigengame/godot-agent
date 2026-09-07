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

## Integrated execution foundation

The checked Model's existing Typed HIR now retains the final specialized program,
entrypoints, callsites and execution closure. Compilation copies those prepared
values; independent imported-Model admission derives the closure again from the
admitted authorities and program. RIR adds selected execution laws, execution
resources and namespace-owned reason/diagnostic definitions. It does not carry
the entire Kernel or Language Definition Bundle.

Initial selection and final closure share one `max_runtime_projection_steps`
counter. The added reason/diagnostic catalog traversal is charged, including rows
that establish ownership but are not retained as execution inputs. Signal lookup
uses an index built during that same request-local traversal. The maintained
minimal quantity case now needs 373 steps and the progression/periodic case 504;
the previous 233 and 318 totals describe the earlier implementation. Permanent
372/373/374 cases cover typed Source refusal, complete compilation and independent
import. Preserving the old total by granting a second allowance is rejected.

Experiment value admission, Runtime execution and independent result replay now
read structured-value laws and their budget from RIR. Runtime also reads selected
nodes, numeric/RNG/scheduler/lifecycle laws, supported profiles and owned refusal
definitions there. Output construction and validation use the request's selected
`ArtifactContract` values. Whole-authority identities still appear as explicit
provenance scalars in output payloads; #875 must remove their obsolete eligibility
and semantic-identity roles.

`test_execution_and_independent_validation_need_no_ingress_authorities` executes
a normally admitted request through a boundary that rejects any attempt to read
its complete Kernel, LDB or authority context. It then validates all output members
through the independent result interpreter and compares their complete bytes
with the unwrapped run. This is a dependency-cut regression, not an alternative
admission path. Restoring the old full-Kernel read in an isolated source copy makes
this test fail at that read. The legal 837/838/839 resource witness separately
verifies the changed semantic identity and actual refusal/success boundary.

Publication now selects its three framing contracts before commit/recovery. Replay
selects its complete owned comparison policy, refusal definitions and comparison
artifact contract at admission; member validation reuses the request's output
contracts. Original-artifact authentication still precedes Experiment admission.
Neither owner consults an ambient catalog to fill a missing selected contract.

Independent bootstrap/reference compilation also derives the new closure. All 34
existing Source vectors were inspected: 21 complete refusal expectations are
unchanged. Each of the 13 successful cases compiles all eight production artifact
classes; four independently derived artifacts (Lock, RIR, Resolved Model and Debug
Map) are byte-identical, with mutual admission of the semantic trio. Only the
existing RIR/Debug identity expectations were rebuilt. A fresh independent pass
after sealing confirms the same computed identities and unchanged Kernel and
package semantic identities: vector-receipt changes introduce no identity cycle.
Six maintained Models publish eight-member Build sets through the CLI. Their eight
Experiment inputs change only exact binding identities and all admit; authored
scenarios, targets, limits and formatting remain unchanged. The intermediate
[validation receipt](evidence/execution-closure/intermediate-validation.json)
records this refresh and the observed public-path checks. Final reviews and CI
remain open.

This broader witness also found a preexisting reference-frontend defect in the
progression/periodic example. The independent consumer omitted Operation roots
called by Formulas, and incorrectly required initialization instruction count to
equal its declared upper bound. It now traverses those roots and nested declared
Operation references, preserves the bound, and checks for overrun. A permanent
case verifies two initialization instructions under the declared bound of three,
four-artifact byte equality and mutual semantic admission. The same unmodified
Source failed independent checking before #874; this is not a production Runtime
regression caused by the closure cut.

A further legal mutation exposes over-selection: changing the structured-value
budget between 65535 and 65536 changes the initial closed RIR for four maintained
pure numeric Models, despite zero structured-value charges and identical complete
observations. The machine resource selector now requires `when: typed-values` and
only emits the limit for programs with a selected typed-envelope profile. The
selector itself still consumes one projection step. Numeric equality executes
without a structured budget in both Runtime and independent replay; absence does
not authorize a fallback or an unlimited budget. Typed programs retain their
explicit resource dependency and the 837/838/839 refusal boundaries.

A nonexecuting Quantity Model has no Event entrypoints and deliberately selects no
scheduler or fixed-value execution laws. An Experiment cannot supply external
facts without a selected entrypoint's external-fact contract. Experiment admission
now returns a resolution refusal at `/model/rir_identity` before constructing
Runtime helpers for this Model. This fixes an eager `scheduler` lookup introduced
by the closure cut, without adding unused laws. The permanent case admits both the
original compile profile and a legal replacement with active Runtime semantics;
neither profile makes the Model executable. Removing only this guard in an
isolated source copy makes both cases fail with `KeyError: scheduler`.

The required test inventory replaces the obsolete 232/233/234 projection-boundary
IDs with 372/373/374, preserving all three refusal/admission obligations and their
complete diagnostic assertions. New closure, applicability, selected-contract and
Publication/Replay cases join the existing CI shards. No inventory obligation is
removed merely to bypass a missing-test failure.

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

The concrete transition inventory for #875 is:

| Retained dependency | Current consumer and propagation | Required deletion boundary |
| --- | --- | --- |
| Authored whole-Kernel/LDB identities and exact Build wrapper | `domain/experiment.py` requires `kernel_identity`, `language_bundle_identity`, and `model.{source_identity,build_receipt_identity,resolved_model_identity,package_lock_identity,rir_identity}`; `domain/model/_binding.py` re-admits the exact published Build set. | Remove provenance-only Experiment prerequisites and their wire-schema, store-resolution and equality branches. Keep independent admission of the selected program and exact bytes actually consumed. |
| Broad evaluator source fingerprint | `domain/runtime/projections.py::evaluator_build_identity` hashes every installed Domain Python file. Its value enters `implementation_identity`, the evaluator manifest and downstream Runtime/reproduction identities. | Remove unrelated compiler/analysis/source inventory from eligibility and semantic execution identity. Truthful implementation provenance may remain in receipts; no source filename allowlist replaces the cut. |
| Whole-authority and Build-derived runtime identity chain | `resolved_runtime_profile` and `reproduction_receipt` propagate whole-LDB, exact Lock/Resolved/RIR envelopes and evaluator-manifest identities; observations bind their resulting receipts. | Split selected execution meaning from exact producing provenance, then remove obsolete propagation and validations from semantic eligibility. Do not erase seed, input order, nominal meaning or actual execution-policy dependencies. |
| Full reproduction equality | `domain/comparison.py::_REPRODUCTION_BINDINGS`, preparation and comparison require whole reproduction equality. `ExactReplayContract.language_bundle_identity` and the comparison payload retain the broad LDB scalar. | Delete irrelevant whole-LDB/build/reproduction gates and obsolete comparison fields. Keep authenticated original artifacts, explicit comparison policy and equality of actual execution inputs. |
| Exact producer-command descriptor checks | `application/experiment_replay.py` passes the current experiment-run descriptor into original publication validation. | Remove unrelated producer-interface changes as semantic Replay prerequisites; retain the exact framing and integrity checks needed to authenticate the original publication. |
| Session ownership of the exact Build wrapper | `application/execution_sessions.py::_ExecutionSession` retains `ExactResolvedModelBinding`; create and revision admission inherit its broad Experiment gates. | Replace that prerequisite with the admitted selected execution input. Retain request snapshots, explicit revision selection, process-local handle invalidation and in-flight ordering. |

This inventory identifies deletion owners and paths; it is not evidence that those
deletions already occurred. #875 must reconcile all affected packaged contracts,
examples and tests, and verify provenance-only mutations through CLI, Replay and
HTTP sessions after removal.

The executable dependency matrix covers the union of all six maintained Models:
11 runtime law groups, 22 nodes, 25 reasons and 25 diagnostic definitions. A
coverage assertion prevents a newly selected definition in those Models from
escaping the explicit mutation witnesses. This verifies selected dependency
admission; it does not by itself prove that each consumer reads the selected value.

Legal diagnostic remapping supplies a separate consumer witness. Swapping numeric
overflow and step-limit diagnostics preserves actual terminal state and exact
charges. Mapping both reasons to the same diagnostic is also admitted by the
unchanged Kernel when the vectors, catalog and package exports agree. The original
decoder incorrectly inferred a unique internal reason from that public code.
Independent charge replay now reports whether the failing instruction actually
exceeds its budget; validation matches this fact against the selected reason
signals for the diagnostic. No new public field or diagnostic uniqueness rule is
needed. This preserves the existing non-budget fault validation scope; it does not
claim independent proof of every non-budget fault's intrinsic cause.

Static structured-value faults also used fixed diagnostic spellings even when an
admitted LDB changed their selected reason mapping. A fault now carries one
intrinsic reason identifier and its pointer; each outward boundary projects the
selected definition. The old `code` alias is removed. The four static reason roots
remain the ones declared by the Kernel; Runtime lookup resolves its reason through
the selected node refusal signal, so a legal reason rename does not add a host
constraint. Permanent cases cover enum, type, record-member and resource refusals,
plus the legal lookup reason rename. The numeric ingress domain check keeps its
own diagnostic path and does not introduce an irrelevant execution dependency.

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
