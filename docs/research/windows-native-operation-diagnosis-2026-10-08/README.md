# Bounded native Windows operation diagnosis (#1136)

Two shared-fixture launches returned **3221225477 / 0xC0000005** after emitting
valid success sentinels. The public CLI returned exit 4 / `operation_failed`.
This confirms a known-native-exception classification gap for
[#1114](https://github.com/aigengame/godot-agent/issues/1114), and a separate
unresolved native fault tracked in
[#1139](https://github.com/aigengame/godot-agent/issues/1139). It does not establish
the fault's root cause or repair any tests. Both concerns feed
[#1124](https://github.com/aigengame/godot-agent/issues/1124).

The [frozen #1113 receipt](../windows-e2e-fixtures-2026-10-07/README.md) remains the
full-run measurement authority: 872 selected, 702 passed, 18 failed, 11 setup
errors and 141 skipped, with no warnings. Fourteen failures were unstructured;
the 11 setup errors came from one shared `_template` failure. These counts are
unchanged. The original audit's eleven observations are a different historical
set. This investigation does not classify all fourteen failures.

## Fixed inputs and observation

- Source: `97c3ea966efd451d5de99a00adbdbd17c2cefd3f` (gda 0.23.0).
- Engine: official `4.6.3.stable.official.7d41c59c4`, explicitly selected as
  `D:\Godot_v4.6.3\Godot_v4.6.3-stable_win64_console.exe`.
- Interpreter: the checkout's `.venv/Scripts/python.exe`, Python 3.13.7;
  pytest 9.0.3, xdist 3.8.0. Native locale cp936, UTF-8 mode 0.
- No `PYTHONUTF8`, `PYTHONIOENCODING`, `GDA_USER_DATA_ROOT` or global profile override.
  Only `PYTHONPATH` selected the frozen source and temporary observer.

The ignored `.audit-cache/1136-frozen97` projection copied regular source bytes
from `git archive`. Its packaged skill-document symlink was materialized from its
authored target because creating a new symlink needs privilege. The selected
tests do not invoke that document. Recorded module paths confirm the frozen
engine runner was used; the projection was not a production source edit.

A temporary `sitecustomize.py` wrapped `gda.core.engine.launch._spawn_streamed`
and observed its actual `Popen` argv, cwd, return code and scoped environment.
It copied bytes returned by the existing `os.read` stream readers, without
changing those bytes. After process reaping and reader joins, decoded copies
were checked against `RunResult.stdout/stderr`; the original result was returned.
The owned `--log-file` was copied before normal cleanup. A temporary pytest
plugin recorded `tests.support.Gda` calls and their public results. No observer,
public envelope, runner contract or production code was added to the repository.

The curated extract (`native-failures.json.gz`, not in the repository) contains both failed native
invocations and two controls: `info` exit 0 and a structured `node-move` refusal
exit 1. Each retains exact argv/JSON, cwd, allowlisted environment, process and
RunResult status, complete native stdout/stderr/log bytes as base64, byte lengths
and SHA-256 digests. Public CLI strings are separately labelled: the existing
helper decoded and normalized them, so they are not raw native byte evidence.
The extract also retains input-project bytes and selected Windows event fields.
It is derived diagnostic JSON, not a full run or JUnit report. All four records
were round-tripped through gzip and their streams compared with the source bytes.

## Trial units, commands and results

One comparison trial means one invocation of this **four-case selection**, not
the full suite. The unchanged source owns the input recipe:
[`_template`](https://github.com/aigengame/godot-agent/blob/97c3ea966efd451d5de99a00adbdbd17c2cefd3f/tests/node/test_e2e_node_instance_internal.py)
builds Weapon/BaseEnemy/Host/Goblin through public commands, then creates
`res://goblin_sprite.gd` extending `Sprite2D`. Its source digest and exact
`project.godot` bytes are in the extract. Trial directories start fresh.

For public-path reproduction, use a checkout of that revision, the recorded
interpreter/dependencies and normal profile/app-data settings. From that source
directory (all `.audit-cache` paths below are disposable output locations):

```powershell
$env:GDA_GODOT='D:\Godot_v4.6.3\Godot_v4.6.3-stable_win64_console.exe'
$env:PYTHONPATH="$PWD\src;$PWD"
$nodes=@(
  'tests/node/test_e2e_node_instance_internal.py::test_node_move_of_a_local_node_under_an_instanced_childs_node_is_refused',
  'tests/node/test_e2e_node_instance_internal.py::test_the_editable_marker_reaches_one_level',
  'tests/export/test_e2e_export_run.py::test_export_run_pack_accepts_a_relative_project',
  'tests/scene/test_e2e_scene_inherited_read.py::test_a_plain_scene_reads_byte_identical'
)
.venv/Scripts/python.exe -m pytest @nodes -p no:cacheprovider -ra --basetemp .audit-cache/serial-1 --junitxml .audit-cache/serial-1.xml
.venv/Scripts/python.exe -m pytest @nodes -p no:cacheprovider -ra -n 4 --dist loadgroup --basetemp .audit-cache/four-1 --junitxml .audit-cache/four-1.xml
```

The observed comparisons used these nodes/options plus `-p trace_cli` and the
temporary observer directory first in `PYTHONPATH`. Their output names were
`1136-comparison-{serial,four}-1` beneath the outer checkout's `.audit-cache`;
cwd was the frozen projection. The initial pilot selected only `$nodes[0]`, used
`1136-shared-serial-1`, and ran from the outer checkout. The unobserved control
removed the observer/plugin and all `GDA_DIAG_*` variables, used the same four
nodes with `-n 4 --dist loadgroup`, and kept cwd at the frozen projection.
Native argv/cwd/env for the two faults are exact in the extract.

| Run (one trial each) | Selected | Passed | Failed | Setup errors | Skipped | Native launches: 0 / 1 / C0000005 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Initial shared-fixture serial pilot | 1 | 0 | 0 | 1 | 0 | 8 / 0 / 1 (9 total) |
| Matched serial selection | 4 | 4 | 0 | 0 | 0 | 20 / 2 / 0 (22 total) |
| Matched four-worker selection | 4 | 3 | 0 | 1 | 0 | 29 / 1 / 1 (31 total) |
| Four-worker public path, observer removed | 4 | 3 | 0 | 1 | 0 | Not observed |

All four selections had zero warnings. The four-worker observed run reached four
overlapping native console launches. Module fixtures were built once serially
but separately per participating worker, so launch counts differ. These are
descriptive denominators, not a controlled failure-rate or concurrency study.
The serial pilot's cwd also differs from the matched comparison.

The pilot failed at `scene-create res://Host.tscn`; the matched four-worker run
failed at the original shared `script-create res://goblin_sprite.gd` call. Both
had `launch_failure=null`, matching Popen/RunResult codes, valid success JSON in
stdout, and only the running-operation diagnostic in stderr. The unobserved
control failed earlier at `node-add`; it establishes that the observer is not
necessary for the public symptom, without proving its native exit code or rate.
The export and plain-scene representatives passed in both observed modes: this
is bounded non-reproduction, not evidence that their historical failures are fixed.

Two direct-engine controls, outside gda CLI and the observer, each ran three
trials. A minimal project containing only the same `project.godot` used frozen
`operations.gd` with `script-create` and JSON
`{"path":"res://goblin_sprite.gd","content":null,"extends_type":"Sprite2D"}`.
The other used a `SceneTree` script that printed `GDA-DIAG-QUIT` and called
`quit(0)`. Both used `--headless --log-file <trial>/godot.log --path <project>
--script <script>`, with cwd at the frozen source. All six native exits were 0;
exact argv are in the extract. This did not produce a smaller failing reproducer.
Trials stopped after the original shared call recurred with complete native
evidence and the observer-free symptom recurred; no automatic retry was added.

## Conclusions and limits

Microsoft defines
[`0xC0000005` as `STATUS_ACCESS_VIOLATION`](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-erref/596a1078-e883-4972-9bbc-49e60bebca55).
Godot's
[4.6.3 console wrapper](https://github.com/godotengine/godot/blob/4.6.3-stable/platform/windows/console_wrapper_windows.cpp)
returns the main process's status. Windows Application Error 1000 records in the
two observed time windows name `Godot_v4.6.3-stable_win64.exe`, `c0000005`, and
offset `0000000003d01771`. A later event in the unobserved-control window has
offset `0000000000535e00`. This is time-window correlation: no wrapper-to-child
PID relationship, native dump or relevant stack was captured.

These invocations launched, parsed their inputs and emitted successful operation
payloads before an abnormal process return. They are not evidence of a missing
binary, quoted-argv failure or the known permission refusal. Success output does
not override a failing process status or prove a crash occurred during teardown.
Absent backtraces do not establish which crash-handler path was active. The
native runtime fault could depend on engine, payload, host or their interaction;
the passing reduced controls do not distinguish those owners. Serial recurrence
shows four-worker concurrency is not necessary, while shared-resource effects
remain unproved. The three ordinary exit-1 refusals are not native crashes.

A read-only historical comparison found no intersecting case IDs between the
seven earlier and twelve later failures whose JUnit traces contain the complete
literal `operation_failed` text. Other truncated traces and the eleven shared
setup consumers are outside that subset. This supports intermittency without
establishing one root cause. No Godot Application 1000/1001 records were found in
the retained log for 2026-10-07; absence is not proof that those runs had no faults.

#1114 owns classification for the captured known exception, with ordinary
nonzero exits kept distinct. #1139 owns diagnosis/repair disposition of the
shared native fault; owner and any upstream report still require evidence.
The unsampled historical failures and sampled non-reproductions remain visible
for #1124. A full four-worker trace could group more failures by native status
if that becomes the next concrete question; it is not a requirement to rerun
the entire suite before routing the two confirmed records. Classification alone
does not imply that all historical failures become `engine_crashed` or pass.

No production, test, schema, ADR or support-baseline change was made. A regression
or repair belongs at the proved owner after diagnosis; no speculative TDD test,
retry, skip, engine-version change, platform layer or Windows CI was added.
