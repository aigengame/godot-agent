# Native Windows fast-tier assessment (#1137)

This frozen assessment compares the **180 failed/error nodes** from the
[#1113 receipt](../windows-e2e-fixtures-2026-10-07/README.md). That receipt owns
the original full selection: **3116 selected / 2735 passed / 177 failed / 201
skipped / 3 setup errors / 0 pytest warnings**.

The measurements below end at `dd0b1154`; they remain historical results.
[#1137](https://github.com/aigengame/godot-agent/issues/1137) records later runs
and follow-ups. [#1124](https://github.com/aigengame/godot-agent/issues/1124)
owns final acceptance and the disposition of confirmed product defects.
Complete fast-tier portability is not an added milestone gate.

## Fixed revisions and results

| Selection | Revision | Passed | Failed | Setup errors | Skipped |
| --- | --- | ---: | ---: | ---: | ---: |
| Historical 180 at base | `8bbb5cc0332b01273c8dbf91d7441efbab4d50b5` | 1 | 175 | 3 | 1 |
| Same 180 at fixture revision | `97c3ea966efd451d5de99a00adbdbd17c2cefd3f` | 1 | 176 | 3 | 0 |
| Same 180 at measured integration | `dd0b1154004a09a53a13d155aabb554d290c8f3c` | 25 | 152 | 3 | 0 |
| Separate two skill controls at base | `8bbb5cc0` | 0 | 2 | 0 | 0 |
| Same two skill controls at fixture revision | `97c3ea96` | 2 | 0 | 0 | 0 |
| Separate junction substitution | `dd0b1154` | 2 | 1 | 0 | 0 |

All comparison selections had zero pytest warnings. [nodes.csv](nodes.csv)
retains all 180 exact IDs, primary causes and historical/base/fixture/integration
outcomes. Every worker collected all requested nodes. These selections are
distinct and their counts are not additive.

## Conditions and evidence limits

- Native Windows 11 build 26200, Python 3.13.7, pytest 9.0.3, xdist 3.8.0;
  preferred encoding cp936, Python UTF-8 mode off. No invocation override of
  `PYTHONUTF8`, `PYTHONIOENCODING`, `GDA_GODOT` or `GDA_USER_DATA_ROOT`.
  Fast tests used their existing placeholder-engine fixture.
- Base and fixture runs used separate `git archive` source projections with the
  same verification environment and dependencies. The skill symlink was
  materialized from each revision's `skills/gda/SKILL.md`; other archive symlinks
  were omitted. Workers checked `gda.__file__`. The integration run used its
  checkout. These were source comparisons, not independent installations.
- `core.autocrlf=true`: the two historical projections retained CRLF bundled
  scripts and failed the LF pin. Integration passed after #1118's source LF
  attributes. Assertions, pins and captured bytes were unchanged.
- Only `test_an_unresolvable_home_on_the_skill_install_dir_writes_under_the_cwd`
  and `test_an_unresolvable_home_on_the_user_data_root_is_a_directory_under_the_cwd`
  in `tests/cli/test_tilde_path_options.py`, plus the separate
  `tests/meta/test_skill_command.py::test_skill_provider_implies_install_and_defaults_to_user_scope`
  control, received a temporary `USERPROFILE`. This prevented
  real/sibling-profile writes; no suite-wide home/app-data override was used.
  The guarded user-data-root pass reflects that protection, **not a repair**:
  the protective basename prevents native `~unknownuser` sibling expansion.
  The guarded skill-write node still failed its separator assertion. Both
  guarded outcomes have altered evidence.
- At this measurement, the other 2936 historical nodes were not replayed.
  Groups identify the first observed failing boundary, not all later assertions.
  No Godot e2e or new macOS/Linux run was made. Later full-run results and engine
  work belong to their linked issues; this report makes no whole-suite or parity
  claim and does not prescribe current issue status.

## Causes and requirement standing

F = failed, E = setup error, P = passed, at `dd0b1154`. Exact IDs are in the CSV.

| Group | Nodes | Outcome | Observed cause and standing |
| --- | ---: | --- | --- |
| `native_path` | 65 | 63 F / 2 P | POSIX literals/slash assertions for native filesystem values; two provenance cases repaired by #1112. |
| `unknown_tilde` | 14 | 13 F / 1 controlled P | Fabricated users do not force failed native home expansion (ADR-0006). |
| `home_only` | 10 | 9 F / 1 P | HOME-only fixtures miss USERPROFILE; perf input repaired by #1119. |
| `live_capability` | 18 | 18 P | Required Live routes delivered by #1118/#1119/#1120. |
| `symlink_privilege` | 28 | 27 F / 1 P | WinError 1314 before assertions; one equivalent alias repaired by #1117. |
| `containment_setup` | 3 | 3 E | Shared fixture cannot create symlinks; junction evidence below. |
| `posix_launcher` | 18 | 18 F | Shebang or `/bin/sh` stand-ins cannot reach pipe/lifecycle assertions. |
| `chmod_denial` | 8 | 8 F | chmod does not produce intended native read/directory denial. |
| `unix_execute` | 2 | 2 F | Intentional Unix execute-mode behavior (ADR-0042). |
| `illegal_filename` | 5 | 5 F | Colon/quote fixture names cannot be created on Windows. |
| `fixture_newline` | 2 | 2 F | Native input writes create CRLF; assertions demand LF (ADR-0018). |
| `bundled_pin` | 1 | 1 P | Strict bundle LF pin restored by #1118's source attributes. |
| `model_depth` | 1 | 1 P | Platform-dependent depth fixture repaired by #1119. |
| `negative_absolute` | 3 | 3 F | `/abs/logic.gd` is not a native absolute path; inadequate ADR-0031 refusal witness. |
| `cross_platform_path` | 1 | 1 F | Simulated Linux platform still uses native Windows `Path`. |
| `readonly_temp_cleanup` | 1 | 1 F | **Supported product defect**: owned read-only restore staging file remains (#1152). |
| **Total** | **180** | **152 F / 3 E / 25 P** | One pass is a protective control. |

Most failures already occurred at the base. The base-to-fixture change touched
20 test files and no product source. Its only historical-node transition was
`tests/project_tree/test_project_tree_inventory.py::test_a_covered_file_is_observed_as_the_capture_reads_it`:
base skipped; the adapted fixture failed because it denied the first inode but
only chmod'd its readable replacement. This is a fixture gap owned by #1153.

For #1152, `tests/project/test_project_file.py::test_a_restore_that_cannot_be_written_is_raised_as_a_typed_error`
raised `ProjectFileRestoreError` and preserved complete target bytes at all three
revisions. `_replace_file` copied the read-only mode to its staging file;
`_discard` suppressed the failed unlink. The defect is owned-temp cleanup.

## Junction equivalence

In a temporary copy of `tests/project/test_res_containment_consistency.py`, only
the two directory symlink creations were replaced with `tests.support.directory_link`
and absolute sibling targets. Product source and every assertion were unchanged.

| Exact test name | Observation and decision |
| --- | --- |
| `test_ownership_wins_when_both_halves_of_the_gate_fire` | Passed; junction preserves the directory-alias witness and all three command envelopes. |
| `test_containment_wins_when_the_spelling_half_fires_too` | Failed containment: `addons/plain/../shared.gd` folds inside the project. Junction is **not equivalent**. |
| `test_the_gate_reads_the_project_as_spelled_rather_than_pre_resolved` | Passed; the root's `alias/../game` spelling remains significant. |

Native Python 3.13 `ntpath.realpath` normalizes `..` before final-path resolution;
the POSIX witness follows the alias first. Symlink privilege does not establish
equivalence. Preserve that POSIX witness and its containment assertion; the
failed substitution supplies no replacement coverage.

## Follow-up ownership and replay

Issues own repair scope, priorities and regression checks:
[#1155](https://github.com/aigengame/godot-agent/issues/1155) home/tilde;
[#1152](https://github.com/aigengame/godot-agent/issues/1152) owned-temp cleanup;
[#1153](https://github.com/aigengame/godot-agent/issues/1153) permission fixtures;
[#1156](https://github.com/aigengame/godot-agent/issues/1156) native paths/bytes;
[#1157](https://github.com/aigengame/godot-agent/issues/1157) filesystem witnesses;
[#1158](https://github.com/aigengame/godot-agent/issues/1158) native child-launch fixtures.
Confirmed product defects require repair or #1124 disposition before parity;
the fixture issues add no acceptance prerequisites. Windows CI remains excluded.

The original four-worker comparison command was:

```text
<verification-venv>/Scripts/python.exe -m pytest tests -m "not e2e"
  -p assessment_subset -p no:cacheprovider -n 4 --dist loadgroup -q -ra
  --basetemp <fresh-task-temp> --junitxml <task-local-output.xml>
```

`PYTHONPATH` selected the task-local plugin, projection `src` and projection root.
The plugin selected CSV IDs before dispatch, checked all 180 existed and recorded
each worker's package source. Its only fixture change was the profile guard:
use each guarded node's `tmp_path`/`monkeypatch`, create
`tmp_path / "assessment-profile-parent" / "protected-user"`, and set only
`USERPROFILE`. The separate skill controls were
`tests/meta/test_skill_command.py::test_skill_provider_implies_install_and_defaults_to_user_scope`
and `tests/meta/test_skill_command.py::test_skill_provider_params_json_drives_the_same_resolution`;
they and the three-case junction experiment ran serially.
Raw logs/JUnit/projections/probes remain ignored under `.audit-cache/1137-*`;
the original full output remains `.audit-cache/1113-final-fast.{xml,log}`.
