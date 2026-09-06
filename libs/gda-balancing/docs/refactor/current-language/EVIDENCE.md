# Refactor evidence portfolio

This portfolio records bounded experiments from 2026-09-06 against commit
`3f68bf3fb26df2ab54351a8ef4e3e167269bdc16`. It supports the current-language refactor
plan; it is not a second Kernel, Language Definition Bundle, conformance suite,
release archive, or proof that the complete target architecture already works.

The revised constraint is explicit: internal historic compatibility and unnecessary
identity coupling must be removed. Closing the Runtime's actual execution dependencies
is a prerequisite to deleting the broad bindings, **not an alternative completion
condition**. The implementation must remove the obsolete checks, fields, readers,
writers and tests after closure. Content-integrity verification, nominal ownership
and truthful evidence provenance retain separate purposes; this portfolio does not
justify keeping compiler provenance or unrelated language content as execution gates.

## Findings and limits

| Experiment | Discriminating observation | Design consequence | Evidence boundary |
| --- | --- | --- | --- |
| [Unified language](evidence/unified/results.json) | The baseline refuses a periodic Model plus progression with `language.resolution_ambiguity`. One current, complete definition per package admits and executes the composed progression-to-periodic path without changing production Python or Kernel primitives. | First converge capabilities; then delete historic package selection. Do not discard old Build or Effect capabilities merely because their version number is older. | Five maintained Models, seven maintained Experiments, one composed Experiment and 41 manifest-bound Operation execution vectors. These are historic observations, not fixed future inventory requirements. |
| [Unified negative](evidence/unified/graph-mutation-results.json) | Removing a real manifest dependency still refuses after all content identities are rebuilt correctly. Wrong Boolean port input and a missing source dependency also refuse. | Package identity simplification must preserve real semantic dependency and type checks. | Three specific refusals. No proof over every malformed graph. |
| [Versionless graph](evidence/identity/results.json) | Namespace-only resolution preserves the actual selected RPG closure and rejects missing/cyclic dependencies and ambiguous capabilities. Input permutations preserve closure. | The internal SemVer selection dimension is not needed by this graph. | A disposable algorithm plus a source hydration shim. The production compiler still consumes version-shaped inputs; this is not a versionless compiler implementation. |
| [Identity amplification](evidence/identity/runtime-results.json) | A compiler build-label change preserves observed Metric and Snapshot values, but rejects the earlier Experiment and changes six Runtime artifact identities. Selected-vector ordering and an unused Effect change also propagate broad identities. | Close execution dependencies, then delete these irrelevant binding gates. Keep provenance informational where appropriate, outside execution equivalence. | One reciprocal RPG Experiment, six Metric samples and nine Snapshot value states per run. Newly bound runs are not claimed as exact Replay. RIR alone is not yet closed: Runtime still reads language-owned reason and rule-budget inputs. |
| [Compiler preparation](evidence/compiler/prepared-results.json) | Request-owned preparation emits byte-identical artifact sets for all five maintained Models while lowering-input calculation falls from three calls to one. Refusals, resource boundaries and mutation isolation remain checked. | Reuse the existing resolved meaning within one request; do not introduce a persistent HIR cache or new public authority. | An isolated source-copy prototype. Separate imported-artifact admission remains. No performance speedup, full CI or concurrency claim. |
| [Compiler counterexample](evidence/compiler/alias-witness.json) | Two projections have equal values and canonical bytes; Formula specialization yields different outputs depending on Python object sharing. | Give operation definitions one owner and derive public projections explicitly. Eliminate reliance on alias-preserving representation tricks. | A baseline-only production specialization witness. The preparation prototype preserves aliases to isolate this problem; it does not fix the ownership defect. |
| [Primitive reduction](evidence/primitives/results.json) | `copy` and `value` have identical laws except the identifier. Comparison-plus-selection matches maximum values, but consumes two steps instead of one. Addition-with-negation fails for a valid subtraction at int64 minimum. | Delete proven duplicate aliases; accept other reductions only with an explicit numeric and resource law and discriminating tests. | Production value-node helper with an independent mathematical oracle. No whole candidate Kernel admission. |
| [Empty-list counterexample](evidence/primitives/empty-results.json) | A proposed typed-equality replacement for the existing emptiness operation refuses the selected real values. | Do not infer that list emptiness is removable from a surface resemblance to equality with an empty list. | The recorded refusal is the desired falsifying result; a zero exit status means the probe reproduced it. |
| [Bounded collection basis](evidence/collections/results.json) | Bounded pure left-fold plus bounded construction expresses stable filtering, count and ordered numeric reduction. Tree and stack evaluators agree on accepted and refused cases; reordering a noncommutative reduction changes its result. | A candidate compositional basis for the present collection gap, subject to authored laws and production conformance before adoption. | A proposed-law prototype, not production Runtime evidence. Shared admission, metering and scalar checks mean evaluator agreement is not fully independent conformance. It does not establish global minimality or full genre completeness. |
| [Dead CLI sink](evidence/retirement/sink-probe-result.json) | Removing the unused single-artifact sink leaves 60 CLI observations byte-identical. The paired raw observations and test receipts are preserved. | Delete the dead mechanism and its inapplicable test rows. Preserve actual multi-artifact publication behavior. | Schema/help/error observations plus the recorded selected tests. This does not authorize deleting Schema 1 conversion for unknown external consumers; current input inventory determines that separate cut. |

## What is preserved

[manifest.json](evidence/manifest.json) records each retained source artifact's original
SHA-256, the tracked SHA-256, and the transformation category:

- `verbatim-original`: original result bytes, unchanged.
- `gzip-verbatim-original`: exact original bytes under deterministic gzip; the original
  digest applies after decompression. Both CLI observation sets are retained this way.
- `sanitized-original`: a receipt whose local path text was replaced. Its tracked digest
  must not be represented as the digest of the original receipt.
- `adapted-paths-only-harness`: original experiment logic with machine-specific source
  and output paths replaced by explicit environment inputs. These historical scripts
  are stored as `.py.txt`; the runner materializes the identical bytes as `.py` files
  in the temporary output directory. They are not executable repository modules and
  do not need a lint exclusion or formatting changes to their experimental logic.
- `new-delivery-tooling`: the reproduction/verification harness and its delivery receipt.

The large copied authorities, source trees and generated Model/Runtime artifacts are
omitted. The unified, identity and compiler scripts regenerate them from the pinned
baseline. The historical result hashes remain evidence of the original run; the
adapted reproduction receipt records the separate delivery-time rerun. No omitted
artifact is claimed to be an independently inspectable member of this tracked bundle.

Compiler preparation includes the disposable patch and scripts because its alias
failure is material to the design. The patch is **not** a proposed production change.
The CLI retirement patch and XML receipts are historical evidence; its original
candidate checkout is omitted and the delivery harness does not rerun that test suite.

## Reproduce

Use the pinned baseline and its Python dependencies. From a package checkout containing
these evidence files, the following creates an isolated baseline checkout and keeps
generated outputs outside it. The interpreter must have the dependencies required by
that baseline; the current package's existing virtual environment was used for the
recorded delivery rerun. No package installation is performed by the harness.

```sh
evidence_dir="$PWD/docs/refactor/current-language/evidence"
probe_python="$PWD/.venv/bin/python"
probe_workspace="$(mktemp -d)"
git clone --shared --no-checkout "$(git rev-parse --show-toplevel)" "$probe_workspace/baseline"
git -C "$probe_workspace/baseline" checkout --detach 3f68bf3fb26df2ab54351a8ef4e3e167269bdc16
"$probe_python" "$evidence_dir/reproduce.py" \
  --package-root "$probe_workspace/baseline/libs/gda-balancing" \
  --output "$probe_workspace/results"
```

Use `--groups collections primitives` (or `compiler`, `identity`, `unified`) for a
bounded subset. Each process has its own imports; prepared compilation uses only a
copied source tree. The harness checks the baseline commit, refuses an output directory
inside the sources/evidence, and requires a fresh output directory. It records each
script hash and exit status, compares compiler artifact/refusal/boundary observations,
and runs the unified probe's explicit acceptance verifier.

All materialized scripts receive `GDA_PROBE_ROOT` and `GDA_PROBE_OUT` from the harness.
They depend on baseline-private production and test interfaces and are intentionally
not a supported developer API. Once implementation changes the baseline, derive the
accepted permanent cases and retire these research harnesses rather than maintaining
another historic compatibility layer.

Run `python evidence/verify_evidence.py` from this directory to verify the tracked
portfolio hashes and exact paired CLI observations. This verifies delivery integrity;
it does not substitute for rerunning an experiment or for the plan's implementation
acceptance criteria.
