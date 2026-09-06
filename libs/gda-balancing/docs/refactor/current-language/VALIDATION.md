# Documentation delivery validation

Validation date: 2026-09-06. Production-code baseline:
`3f68bf3fb26df2ab54351a8ef4e3e167269bdc16`. This delivery changes documentation and
adds an evidence reproduction harness. It does not implement the planned production refactor.

| Check | Observed result | Limit |
| --- | --- | --- |
| Evidence manifest verifier | 41 recorded files and 60 paired CLI observations verified | Integrity and paired observations, not full conformance |
| Portable probe rerun | All 13 derived JSON result records match the retained original values | See the [reproduction receipt](evidence/reproduction-receipt.json); historical sink pytest receipts were not rerun by this harness |
| Ruff check and format | Both delivery Python tools pass | Historical `.py.txt` probes preserve experimental logic; they are not repository Python modules |
| Existing isolation and layer tests | 38 passed | No complete Runtime or real Godot acceptance claim |
| Existing CI inventory check | 1,747 current tests and 385 package vectors; no missing, overlapping, uncovered or unexpected entries | Collection coverage, not execution of every collected test |
| Requirement/source reconciliation | 164 captured clauses retain original IDs, text and source links; 143 production files are routed; all genre table rows remain unchanged | Routing is not clause-level implementation acceptance |
| Issue graph and publication | 14 child issues have an acyclic initial blocking graph; #874 → #875 → #879 enforces closure followed by deletion | GitHub owns later live status and acceptance changes |
| Prior issue reconciliation | 12 amended bodies were read back exactly; state, labels, milestone and title were preserved | The notices supersede only the identified outdated clauses |
| Local documentation | Relative Markdown targets exist; no local-user paths or unexpanded issue placeholders; authored-file whitespace checks pass | External-source findings retain their stated historical research bounds |

The preserved `compiler/prototype.patch`, `retirement/sink-deletion.diff` and
`unified/probe.py.txt` retain their original whitespace. Git reports patch context blank-line
markers and one archived probe line as trailing whitespace; these three archived files are
excluded from the authored-file whitespace check and instead verified by manifest hashes.
They are not silently reformatted or presented as production changes.

Reproduction and integrity commands are documented in [EVIDENCE.md](EVIDENCE.md).
Additional existing package checks, run from the package directory:

```sh
.venv/bin/python -m pytest -q tests/test_isolation.py tests/test_layer_dependencies.py
.venv/bin/python tools/ci.py verify-inventory --report /tmp/balancing-current-inventory.json
```

The documentation PR's exact-head checks own remote CI results. A passing documentation
PR cannot close #865 or the production implementation issues; it closes only #866 after merge.
The final implementation must satisfy #879 against its actual shipped artifacts.
