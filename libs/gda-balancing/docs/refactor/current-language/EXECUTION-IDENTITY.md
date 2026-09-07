# Delete obsolete execution bindings

Implementation record for #875 (S5b), after #874 was independently reviewed and
merged into the shared development branch as `2a6c89cde`. This record fixes the
implementation contract; it does not claim that deletion or acceptance is complete.
The issue and its delivery PR own live acceptance.

## Problem and discriminating evidence

At the reviewed #874 head, changing only the compiler label preserves the complete
RIR bytes but makes the old Experiment fail at its exact Build binding. Reversing
the selected `core.quantity` conformance-vector order also preserves RIR bytes,
package semantics and every vector definition, but changes whole-LDB provenance
and makes the old Experiment fail its authority binding. Updating those bindings
restores equal accepted observations (eight Events, nine Snapshots and six Metric
samples in the bounded witness), while changing six or seven output identities.
The production Replay admission checks refuse the original results in both cases.
These are Domain execution and result-validation witnesses; they do not establish
public CLI or authenticated-publication acceptance of this deletion.

#874 already closes the selected execution laws, nodes, reasons, Diagnostics and
applicable resources. S5b must now remove the old prerequisites and their indirect
paths. In particular, result validation currently reconstructs the installed
evaluator and reproduction record, then requires supplied records to equal them.
Deleting only the direct Replay comparison would leave this hidden prerequisite.

## Selected execution and producing provenance

Use the existing RIR semantic identity and the existing Resolved Runtime profile
artifact identity. Do not introduce another digest, compatibility route, source
allowlist or replacement receipt.

| Owner | Required endpoint |
| --- | --- |
| Model | `admit_rir` independently admits one canonical RIR under the admitted current authorities. `AdmittedRir` contains detached RIR bytes and its existing content/semantic identities. It contains no Build receipt, Package Lock, Resolved Model wrapper or authority catalog. |
| Experiment | Authored `model.rir_semantic_identity` binds the admitted program. Delete root Kernel/LDB identities and the old Source/Build/Lock/Resolved/exact-RIR tuple. Preserve all scenario, seed, stream, assignment, input, ordering, capability and policy checks. |
| CLI / Application | Check, run and Replay receive an explicit required RIR file. No committed-store discovery, sibling-file guessing or old-input fallback supplies the program. |
| Execution session | Compile Model Source and admit its RIR through the same Model owner. Revisions retain that admitted program. Preserve explicit revisions, detached inputs, ordering and stale-handle refusal. |
| Runtime | The existing Resolved Runtime profile contains clean Experiment identity, RIR semantic identity and the complete selected Runtime profile/definition identity. Remove whole-authority/Build wrappers, evaluator identity, platform and duplicate RNG fields. |
| Producer provenance | The Evaluator Capability Manifest records the implementation label, complete installed-source fingerprint, platform and actual capabilities once. Delete the redundant `implementation_identity`; manifest content identity already identifies this record. |
| Results | Trace, Snapshot, Metric, success, Verdict and terminal audit bind actual execution meaning. Delete their producer/reproduction links and the redundant Metric `source_provenance` object; preserve actual per-sample provenance and every journal, refusal, rollback and cross-artifact check. |
| Publication | The authenticated Artifact-set manifest already associates the actual outputs, semantic profile and producer manifest. Delete the Reproduction receipt artifact and all of its schema, contract, export, constructor, member and consumer paths. |
| Replay | Authenticate original bytes and their original descriptor/transaction anchors. Delete equality against the current command descriptor and complete producing provenance. Compare actual execution identity and observations under the selected comparison policy. |
| Evidence | Evaluable prerequisites connect the existing RIR semantic identity, Experiment, Runtime profile, producer manifest and authenticated run publication. Delete mandatory Source/compiler/Build-publication execution prerequisites. Build provenance remains in its own records; deferred trust activation does not change. |

The Reproduction receipt has no unique surviving fact: seed, streams, external
input and ordering are authored Experiment inputs; the selected program and
policy have existing identities; producer facts belong to the evaluator manifest;
atomic Artifact-set membership associates their publication. No join receipt
replaces it. An authenticated producer record establishes its recorded provenance,
not new verifier trust or completion of #542–#544.

## Admission and ownership constraints

Independent RIR admission starts from admitted owner definitions, applies Formula
specialization and derives the complete selected closure again. A self-consistent,
reidentified candidate is insufficient. Keep declaration sorting/uniqueness,
nominal ownership, recursive Types, Formula graphs and parameter maps, entrypoints,
call sites, initialization and the single projection budget. Exact Build/trio
validation remains a Build concern and reuses the same Model semantic judgment.

Extract the existing selected namespace catalog inside Model so execution does not
construct a fake or partial Package Lock artifact. The Build serializer can use
that same private catalog. Do not add another public executable representation.

Formula pairs still render identically and parse to the same canonical body under
bADR-0024. RIR admission selects notation from the body's actual Operation
coordinates; unrelated notation must not become a new execution prerequisite.
Source and Build retain their original authored-context checks.

For new execution, check the installed evaluator's actual capabilities. For an
original result, validate its supplied producer record, capability coverage and
relation to the selected execution. Recompute semantic inputs, never the original
producer from current host constants. Preserve all independent journal and terminal
validation; removing provenance equality does not authorize invalid outcomes.

## Implementation and acceptance order

1. Land the Model admission/catalog foundation and the closed machine contracts.
   Keep intermediate failures explicit on the issue branch; they are not delivery.
2. Connect Experiment and public RIR ingress, then update Runtime/results, Replay
   and Evidence against those shared interfaces in isolated owner worktrees.
   Integrate their commits serially and check real owner boundaries after each.
3. Replace obsolete expectations in current tests and maintained sources. Reconcile
   the glossary, architecture, affected bADRs, CLI help/schema, HTTP language,
   Godot example consumers and packaged authorities. Retain diagnostic and tamper
   assertions; do not remove obligations to make inventory checks pass.
4. Prove provenance-only compiler/implementation/platform, unselected-package and
   selected-vector changes preserve semantic identities and complete observations
   through CLI, authenticated Replay and sessions. Changed bytes and producers must
   still change their exact provenance records.
5. Prove actual law/resource/nominal/profile, seed/stream, assignment, input and order
   changes alter the relevant semantic identity or refuse. Keep coherent tampering,
   invalid journals/rollback, unsupported capabilities and stale handles rejected.
6. Search production source, machine contracts, resources and consumers for every
   enumerated obsolete field/helper/route. Run the required source, wheel and public
   checks, then independent Standards, Spec and domain-architecture reviews.
   Complete deletion and public validation are mandatory before closing #875.

Rollback restores code, packaged authorities, authored sources, current evidence
and consumers together to the reviewed development baseline. It does not keep a
legacy path in the new implementation. Final development integration still waits
for the owner's accumulated review; this work does not merge into main or release.
