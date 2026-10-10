# Native Windows fast-tier assessment (#1137)

This is a frozen assessment and follow-up definition, not a product repair or
full Windows fast-tier acceptance. The [#1113 receipt](../windows-e2e-fixtures-2026-10-07/README.md)
owns the original measurement: **3116 selected / 2735 passed / 177 failed / 201
skipped / 3 setup errors / 0 pytest warnings**. That measurement is unchanged.

The comparison below selects precisely its **180 failed/error nodes**. Most
failures already occur at the earlier base. One newly activated fixture exposes
an incomplete read-denial setup. One supported project-write cleanup defect is
confirmed; [#1152](https://github.com/aigengame/godot-agent/issues/1152) owns its
repair. [#1153](https://github.com/aigengame/godot-agent/issues/1153) proposes the
inventory fixture repair. Complete fast-tier portability is not a new milestone
20 gate. [#1124](https://github.com/aigengame/godot-agent/issues/1124) owns final
parity and the disposition of confirmed product defects.

## Fixed revisions and observed outcomes

| Selection | Revision | Passed | Failed | Setup errors | Skipped |
| --- | --- | ---: | ---: | ---: | ---: |
| Historical 180 at base | `8bbb5cc0332b01273c8dbf91d7441efbab4d50b5` | 1 | 175 | 3 | 1 |
| Same 180 at fixture revision | `97c3ea966efd451d5de99a00adbdbd17c2cefd3f` | 1 | 176 | 3 | 0 |
| Same 180 at current integration | `dd0b1154004a09a53a13d155aabb554d290c8f3c` | 25 | 152 | 3 | 0 |
| Separate two skill controls at base | `8bbb5cc0` | 0 | 2 | 0 | 0 |
| Same two skill controls at fixture revision | `97c3ea96` | 2 | 0 | 0 | 0 |
| Separate junction substitution experiment | `dd0b1154` | 2 | 1 | 0 | 0 |

All new selections had zero pytest warnings. Every worker collected all requested
historical nodes; none was missing. [nodes.csv](nodes.csv) records each node once,
its primary cause and its original/base/fixture/integration outcome. It contains
no traceback or raw captured output. The selections are distinct, not additive
suite totals.

The fixed base-to-fixture diff changes 20 test files and no `src/gda`, `scripts`
or `pyproject.toml` product source. Within the historical selection, the only
outcome transition is
`tests/project_tree/test_project_tree_inventory.py::test_a_covered_file_is_observed_as_the_capture_reads_it`:
base skips because mode 000 remains readable; the fixture revision's DACL locks
the first inode, then the replacement inode is only chmod'd. It is readable on
Windows, so settlement correctly reports one skipped file instead of two.
This is an incomplete fixture adaptation, not a proved inventory product defect.

The two separate skill controls are
`tests/meta/test_skill_command.py::test_skill_provider_implies_install_and_defaults_to_user_scope`
and `tests/meta/test_skill_command.py::test_skill_provider_params_json_drives_the_same_resolution`.
They show the local HOME/USERPROFILE and native installed-path assertion repairs
working under the disclosed protection. They do not establish a fresh package
installation or unprotected baseline result.

## Conditions, controls and limits

- Native Windows 11 build 26200, Python 3.13.7, pytest 9.0.3, xdist 3.8.0; native
  preferred encoding cp936, Python UTF-8 mode off. No `PYTHONUTF8`,
  `PYTHONIOENCODING`, `GDA_GODOT` or `GDA_USER_DATA_ROOT` invocation override.
  Fast tests retain their own existing placeholder-engine fixture.
- The two fixed revisions run from separate `git archive` regular-file source
  projections with the same current `.venv` and dependencies. The bundled skill
  symlink is materialized from that revision's authored `skills/gda/SKILL.md`.
  Other archive symlink entries are omitted. Workers verified `gda.__file__`
  points into the intended projection; the current comparison uses the integration
  checkout. These are source comparisons, not independent package installations.
- `core.autocrlf=true` remains in effect. The historical bundled script files
  retain CRLF bytes and both fixed projections fail their LF pin. Current
  integration passes after #1118's two explicit source LF attributes. No pin,
  raw output or assertion is normalized for this experiment.
- No suite-wide HOME/USERPROFILE/APPDATA or text-mode mask is used. Only these
  two historical write nodes receive a temporary USERPROFILE before their own
  fixtures execute: `test_an_unresolvable_home_on_the_skill_install_dir_writes_under_the_cwd`
  and `test_an_unresolvable_home_on_the_user_data_root_is_a_directory_under_the_cwd`
  in `tests/cli/test_tilde_path_options.py`. The separate old HOME-only user-scope
  skill control receives the same protection. This prevents writes into a real
  or inferred sibling user profile. The test's own monkeypatch can override it.
- On this host, Python can infer `~unknownuser` as a sibling of USERPROFILE when
  its basename matches USERNAME. The protective profile has a different basename,
  so expansion stays literal. **The one passing historical user-data-root node
  is caused by this protection, not a repair.** The skill write node still fails,
  now at its literal separator assertion. Both guarded nodes have altered
  evidence; do not claim unqualified native baseline or repair acceptance.
- The other 2936 historical nodes were not replayed. This selection does not
  prove there are no new failures elsewhere or that a complete native fast tier
  is green. Cause groups describe the first observed failing boundary, not proof
  that all subsequent assertions or supported workflows are correct. Privilege
  failures do not establish what a test would do after successful link creation.
- #1139 is deferred by the maintainer and was not investigated. No real Godot
  e2e or new macOS/Linux execution ran in this assessment. The Unix checks below
  are proposed repair checks, not claimed results.

## Causes and requirement standing

Group keys join to `nodes.csv`. Counts describe the 180 historical problem nodes.
F = failed, E = setup error, P = passed. Except where indicated, the standing is
a platform fixture/assertion issue, not a confirmed product defect.

| Group | Nodes | Current outcome | Cause and standing |
| --- | ---: | --- | --- |
| `native_path` | 65 | 63 F / 2 P | POSIX-looking literals or slash assertions for native filesystem values. #1112 repaired two version/provenance cases. Preserve `res://` spelling separately. |
| `unknown_tilde` | 14 | 13 F / 1 controlled P | Fabricated account names do not force native unresolvable-home behavior; ADR-0006 preserves a literal only when this host cannot expand it. |
| `home_only` | 10 | 9 F / 1 P | HOME-only fixtures miss Windows USERPROFILE. #1119 repaired the perf budget input. |
| `live_capability` | 18 | 18 P | Previously awaited supported Live routes, now delivered by #1118/#1119/#1120. No duplicate repair. |
| `symlink_privilege` | 28 | 27 F / 1 P | Direct symlink creation raises WinError 1314. #1117 repaired the equivalent daemon directory alias. Other cases need semantic review. |
| `containment_setup` | 3 | 3 E | Shared monorepo fixture cannot create symlinks. Junction equivalence is assessed below, case by case. |
| `posix_launcher` | 18 | 18 F | Directly executed shebang or `/bin/sh` stand-ins cannot reach their real pipe/capture/lifecycle assertions under native CreateProcess. |
| `chmod_denial` | 8 | 8 F | chmod does not create intended Windows directory/read denial; includes the replacement-inode case routed to #1153. |
| `unix_execute` | 2 | 2 F | Intentional Unix execute-mode behavior (ADR-0042). chmod 644 does not mean Windows non-runnable; no product execute-bit emulation. |
| `illegal_filename` | 5 | 5 F | Real colon/double-quote fixture names cannot be created on Windows. Preserve Unix filename cases; parser strings and native legal files are separate witnesses. |
| `fixture_newline` | 2 | 2 F | Native `write_text` creates CRLF input, then assertions demand raw LF. ADR-0018 preserves source terminators. |
| `bundled_pin` | 1 | 1 P | Source checkout LF fixed by #1118. Keep strict raw byte pins. |
| `model_depth` | 1 | 1 P | #1119 repaired a platform-dependent model-depth fixture; the deeper rejection is already typed. |
| `negative_absolute` | 3 | 3 F | `/abs/logic.gd` lacks a drive/UNC and is not a native absolute `Path`. It does not witness ADR-0031's absolute-address refusal. |
| `cross_platform_path` | 1 | 1 F | Linux platform simulation still constructs native Windows `Path` values. It is not a real Linux run. |
| `readonly_temp_cleanup` | 1 | 1 F | **Confirmed supported product defect**, owned by #1152: refused restore leaves its own read-only temporary file. |
| **Total** | **180** | **152 F / 3 E / 25 P** | One of the 25 passes is controlled, not a demonstrated repair. |

Representative exact IDs for every group are in the CSV. Source anchors are
`gda.core.project.paths` and ADR-0006 for home/containment,
`gda.core.contract.values.normalize_path` for native filesystem values,
`gda.core.engine.user_data` for placement, `tests.support` for the existing
home/permission/link seams, and the implicated test modules themselves.

For example, `tests/runtime/test_user_data_placement.py::test_refusal_diagnostics_name_binary_user_data_and_log_path`
uses directory chmod and a spawn guard returning `None`. Because native directory
creation is still permitted, it unexpectedly reaches that guard and fails at
`None.stdout`. This is not a real Popen result or evidence that launch must accept
`None`. A proper denial fixture must prevent that path before launch.

The #1152 node is
`tests/project/test_project_file.py::test_a_restore_that_cannot_be_written_is_raised_as_a_typed_error`.
At all three revisions it raises `ProjectFileRestoreError`, preserves the complete
engine-written `project.godot`, and fails the final no-residue assertion.
`_replace_file` copies the read-only target mode to the staged file; replacement
is refused and `_discard` suppresses the unlink error on that read-only file.
The supported defect is cleanup of the owned staged file, not data loss or a
missing typed refusal. Repair only that ownership boundary.

## The three junction decisions

An ignored copy of `tests/project/test_res_containment_consistency.py` replaced
only the monorepo fixture's two directory symlink creations with the existing
`tests.support.directory_link`, using absolute sibling targets. All three tests'
assertions and product sources remained unchanged.

| Exact test name | Native observation | Decision |
| --- | --- | --- |
| `test_ownership_wins_when_both_halves_of_the_gate_fire` | Passed; both ownership and containment fire, all three command envelopes agree. | Junction preserves this directory-alias witness. |
| `test_containment_wins_when_the_spelling_half_fires_too` | Failed at `path_outside_project(...) is not None`; target `addons/plain/../shared.gd` is folded inside the project. | Junction is **not equivalent**. Do not weaken the containment assertion or count this substitution as coverage. |
| `test_the_gate_reads_the_project_as_spelled_rather_than_pre_resolved` | Passed; the root's `alias/../game` spelling remains significant. | Junction preserves this directory-alias witness. |

Python 3.13's native `ntpath.realpath` normalizes `..` before final-path resolution.
The middle POSIX witness follows the alias before `..`, reaching a different
sibling file from its lexical spelling. Native symlink creation privilege alone
does not remove this path-resolution difference. Preserve the real POSIX
link-plus-`..` witness. Use `symbolic_link`'s explicit WinError-1314 gate for cases
that require a real symlink, but do not assume a privileged Windows run gives
this specific POSIX witness. A separate native containment-before-spelling witness
would need validation and must not claim to prove correction to a different file.

## Small follow-ups, in execution order

These proposals are not new prerequisites or a commitment to repair all 180
nodes. Issues own scope; owners below identify code/test responsibility.

| Priority | Owner and smallest slice | Validation and constraints |
| --- | --- | --- |
| P1 | CLI tilde fixtures: first the two host-writing nodes in `tests/cli/test_tilde_path_options.py`. | Force the negative condition at the existing expansion seam; keep positive native expansion through `home_env`. Verify no real/sibling-profile writes; preserve Unix literal-directory and structured-refusal behavior. |
| P2 | Project restore: **#1152**. | Native read-only refusal, owned-temp cleanup, unchanged target bytes and typed error; Unix project-file atomic/changed-token/mode tests. Repair or explicit #1124 disposition before parity. |
| P2 | Inventory replacement-inode fixture: **#1153** (needs triage). | Use `unreadable` on both inodes with actual denial probes through settlement; preserve replacement/count assertions and permission restoration. Native focused case plus Unix inventory/permission checks. |
| P2 | `tests/runtime/test_user_data_placement.py`: one denial group at a time, then metadata/harness read denials as separate slices. | Reuse `unwritable`/`unreadable` and their probes or existing prefix-specific denial doubles for pure formatting. Keep typed failures, bytes, restoration and no-launch assertions; same relevant Unix tests. |
| P2 | Containment: the two equivalent directory-alias cases first; other aliases require separate equivalence checks. | Reuse `directory_link`; retain every ordering/envelope assertion. Preserve POSIX link-plus-`..`, file/dangling/retarget symlink witnesses and explicit native privilege gates. Unix containment/project tests and `test_the_stated_reissue_survives_a_link_spelled_owner` e2e. |
| P2 | `tests/runtime/test_launch.py`: adapt only temporary fake-engine launch at its existing Popen seam. | Keep a real child, pipes, split UTF-8 bytes, timeout/abort/reaping and owned-PID checks. Run the same cases on Unix; no public arbitrary-process launcher or canned mock substitute. |
| P2 | Three script-run absolute-address fixtures and six placement-result assertions recorded by #1114; other command groups separately. | Native absolute temporary input and semantic `Path` expectations only for filesystem fields. Preserve `res://`, schemas, sentinel payloads and opaque captured bytes. No global slash normalization. |
| P3 | Two harness newline fixtures; native legal names and Unix execute checks. | Explicit LF input bytes or exact native before/after bytes, according to the asserted contract. Keep raw bundle pins. Preserve Unix filename/execute coverage and add meaningful native witnesses, not blanket skips. UTF-8 decoding belongs at capture sites, not a suite-wide environment mask. |

There is no need for a new platform fixture registry, broad test reorganization,
CJK/code-page fallback, product-path normalization or Windows CI.

## Replay recipe and compact evidence

The native command for each 180-node run was:

```text
<verification-venv>/Scripts/python.exe -m pytest tests -m "not e2e"
  -p assessment_subset -p no:cacheprovider -n 4 --dist loadgroup -q -ra
  --basetemp <fresh-task-temp> --junitxml <task-local-output.xml>
```

`PYTHONPATH` selects the task-local plugin, the chosen projection's `src`, and
the projection root. The temporary plugin selects the node IDs from `nodes.csv`
before dispatch and asserts all 180 exist; workers record the resolved package
path. Its only fixture mutation is the per-node USERPROFILE guard described
above. To reproduce that guard, create a test-only autouse fixture, obtain each
guarded node's `tmp_path` and `monkeypatch`, create
`tmp_path / "assessment-profile-parent" / "protected-user"`, and set only
USERPROFILE to it. Keep other profile inputs and native decoding unchanged.
The same two skill nodes run serially through this guard; the junction experiment
selects only the three named tests in the temporary fixture copy, serially.

Raw output remains ignored under `.audit-cache/1137-*`; the historical full fast
output remains `.audit-cache/1113-final-fast.{xml,log}`. The curated CSV and this
report retain the necessary classification and decisive observations without
committing the raw investigation. SHA-256 values identify the local JUnit files:

| Local file | SHA-256 |
| --- | --- |
| `1113-final-fast.xml` | `e81b0b0e9769d97d4f25b20ce34a2367a665d1b1e9b820593d64873f88ad40c7` |
| `1137-base-historical-180.xml` | `4923aeda4da942ff2dc5cf0a0354f4e455a8600d4f4170431fef9360fcdcccb0` |
| `1137-fixture-historical-180.xml` | `d68a2f3ceb0ed1ff34631a721d76c807df71f063332cba8cb22a703555e1f69d` |
| `1137-current-historical-180.xml` | `57aa8f3cbed479aa9f1e07139901c6f31df181c96a858f721a49e8d0f26efe8e` |
| `1137-junction.xml` | `b33e14548623f14c8807afa8b4c89116942966573686eab32e767551e6819480` |
