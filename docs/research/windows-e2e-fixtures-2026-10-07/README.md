# Native Windows fixture verification (#1113)

This is a frozen verification receipt, separate from the original
[859-case audit](../windows-platform-audit-2026-10-06.md).
The integration base is `8bbb5cc0332b01273c8dbf91d7441efbab4d50b5`.
The fixture implementation tested here is
`97c3ea966efd451d5de99a00adbdbd17c2cefd3f`.

## Environment and reproduction

Windows 11 build 26200; checkout-managed Python 3.13.7, gda 0.23.0,
pytest 9.0.3 and pytest-xdist 3.8.0. Engine: standard official Godot 4.6.3,
`D:\Godot_v4.6.3\Godot_v4.6.3-stable_win64_console.exe`.
Python's native locale encoding is cp936 (GBK), UTF-8 mode is off. `PYTHONUTF8`,
`PYTHONIOENCODING` and `GDA_USER_DATA_ROOT` are unset. The invocations do not
override HOME or USERPROFILE. Individual home/app-data cases isolate their own
child environment. The packaged SKILL.md link is a native link; this host cannot
create new file symlinks without privilege (WinError 1314).

From the recorded checkout, after synchronizing its environment:

```powershell
$env:GDA_GODOT='D:\Godot_v4.6.3\Godot_v4.6.3-stable_win64_console.exe'
.venv/Scripts/python.exe -m pytest tests -m e2e -n 4 --dist loadgroup --basetemp .audit-cache/1113-final-e2e -ra -p no:cacheprovider --junitxml .audit-cache/1113-final-e2e.xml > .audit-cache/1113-final-e2e.log 2>&1
```

The base uses the same command with `1113-base-e2e` output names. These paths are
local setup values. Current engine configuration remains `--godot` > `GDA_GODOT`.
The cache contains uncommitted run logs and diagnostic probes.

## Full selections

| Revision / selection | Selected | Passed | Failed | Setup errors | Skipped | Warnings |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Integration base, Windows e2e | 871 | 553 | 162 | 32 | 124 | 166 |
| Fixture implementation, Windows e2e | 872 | 702 | 18 | 11 | 141 | 0 |
| Fixture implementation, supplementary Windows fast tier | 3116 | 2735 | 177 | 3 | 201 | 0 |

The extra e2e case separates directory-cache aliases from file-symlink aliases.
[base-e2e.xml.gz](base-e2e.xml.gz) and [native-e2e.xml.gz](native-e2e.xml.gz)
contain the original JUnit bytes, compressed without filtering failures.
The supplementary raw results stay in `.audit-cache/1113-final-fast.xml`.
To reproduce that selection,
remove `GDA_GODOT` and replace `-m e2e` with `-m 'not e2e'`, using distinct output
names. The existing fast-tier fixture supplies its placeholder engine.
That tier is not green: remaining Unix stand-ins, path assertions, Live assumptions
and symlink-privilege cases are outside this local-e2e slice. No complete native
fast-tier base comparison was performed.

The final e2e run has no setup error from the repaired platform assumptions and no
reader-thread decode exception. Its **11 setup errors remain in the total**:
one shared `test_e2e_node_instance_internal._template` failed in the public
`gda script create` call with an unstructured `operation_failed`, preventing 11
tests from reaching their bodies. Its cause is unresolved; the earlier full run
at `dc13c019` reached those bodies (711 passed, 15 failed, 146 skipped, no setup
errors or warnings). This is not evidence of a particular native crash status.
One bounded control of the affected module fixture at the implementation revision
passed (one case); it does not replace the 11 original setup errors in the table.

The 18 failures comprise two existing Live platform rejections, two reproducible
permission-error classification failures tracked in
[#1134](https://github.com/aigengame/godot-agent/issues/1134), and 14 unstructured
operation failures. The latter remain unexplained and are retained for follow-up;
they are not reclassified as successful retries or assigned a cause from symptoms.
The permission probe confirmed actual file/subdirectory denial, empty before/after
contents and restored access. The original `save_failed` assertions stay intact.

The 141 skips are: 115 current Unix Live-stack cases; 15 macOS artifact-evidence
cases; five missing matching-template cases; one Linux/BSD-only template fixture;
three native symlink-privilege cases; one flat user-data-shape case; one existing
POSIX-only value case. The host holds 4.3 templates, not matching 4.6.3 templates.
Junction tests execute where directory-alias semantics are equivalent; actual
file links and the lexical dot-dot symlink case keep their explicit privilege gate.

## Focused and Unix evidence

The two known skill fixtures failed at the base under a disposable invocation
home guard. After repair, both passed without an invocation-wide home override.
The combined MCP project-context, skill and surface-sync selection passed all 56
cases. Native ACL/user-data/read/write coverage passed 10 cases and skipped one
flat-shape case; the newly executable project-create cases exposed #1134.
Focused commands and intermediate logs remain in `.audit-cache/1113-*`.

```powershell
.venv/Scripts/python.exe -m pytest tests/mcp/test_mcp_project_context.py tests/meta/test_skill_command.py tests/meta/test_skill_surface_sync.py -ra
.venv/Scripts/python.exe -m pytest tests/runtime/test_e2e_user_data.py tests/scene/test_e2e_scene.py::test_scene_create_unwritable_directory_yields_structured_save_failed tests/script/test_e2e_script.py::test_script_get_unreadable_file_is_path_not_found_not_empty_source -ra
```

Actual Linux regressions use the existing workflow, with real Godot and matching
export templates; no Windows workflow was added. At `dc13c019`,
[CI run 37604991021](https://github.com/aigengame/godot-agent/actions/runs/37604991021)
passed lint, typing, build, 3112 fast tests (four skips, one warning) and 831 e2e
tests (41 skips). The fixture implementation has a second actual Linux run:
[CI run 37606817853](https://github.com/aigengame/godot-agent/actions/runs/37606817853),
which also passed all four jobs: lint, typing, unit/build and real-engine e2e,
with the same 3112 fast passes / four skips / one warning and 831 e2e passes /
41 skips. A Windows CI or native export-success claim is not part of this receipt.
