# Windows platform audit

Date: 2026-10-06 (Asia/Shanghai). Source revision: `6d5da3df36d7bf3ba6972c485ef955a2bf8c1926`.
Scope: the root gda domain (`gda`, `gda-mcp`, `gda-daemon`, and the bundled gda skill).
The balancing library and example game's capabilities are separate domains and are not included.

## Findings

Windows lacks the entire live stack that macOS supports. The headless path has Windows-specific code, but its real Windows coverage is incomplete. This audit also reproduces defects in the CLI output encoding and MCP path handling. Source findings, small native probes, full e2e results, and unverified risks must be counted separately.

### Command surface

The checked-out source's `build_surface_manifest(app)` returns 80 public commands:

| Execution kind | Commands | Commands excluded on Windows by published constraints |
| --- | ---: | ---: |
| `headless` | 56 | 5 daemon lifecycle commands |
| `live` | 19 | 19 |
| `export` | 1 | 0 |
| `artifact_smoke` | 1 | 0, but Windows behavior is not promised |
| `import` | 2 | 0 |
| `script_run` | 1 | 0 |
| Total | 80 | 24 |

Thus 24/80 commands (30%) explicitly exclude Windows. The other 56 commands have no Windows exclusion; that is not a claim that all 56 pass on Windows. In particular, the `headless` kind includes five daemon commands that still enforce the platform gate. The authoritative constraint predicate applies to every `live` command and every operation whose name starts with `daemon-` (`src/gda/execution.py:92-99`).

The excluded commands are:

- `daemon install`, `start`, `status`, `stop`, `uninstall`, and `wait-ready`.
- `game tree`, `find`, `get`, `rect`, `set`, and `call`.
- `input key`, `mouse-click`, `mouse-move`, `action`, `tap`, and `sequence`.
- `screen capture` and `frames`.
- `perf monitors` and `monitor`.
- `diag errors` and `logger tail`.

### Confirmed capability and implementation gaps

| Area | Windows gap relative to macOS | Evidence and limits |
| --- | --- | --- |
| Live operations and daemon lifecycle | All 24 constrained commands reject native Windows with `live_unsupported_platform`. There is no running-game control, input simulation, viewport capture, runtime diagnostics, or performance monitoring. Even standalone harness install/uninstall CLI commands are gated. | `src/gda/live_runner.py:55-61`; `src/gda/commands/daemon.py:544-555`; lifecycle callers at lines 909, 1080, 1125, 1178, 1210. Deliberate boundary in `docs/adr/0021-gda-daemon-transport-discovery-and-live-version-floor.md`. |
| IPC and discovery | The implementation has only UDS transport and POSIX file-lock liveness. Removing the Windows gate alone cannot provide support. | CLI socket: `src/gda/live_runner.py:80`; daemon control socket: `src/gda/commands/daemon.py:614`; daemon socket bind: `src/gda/daemon/server.py:224`; harness `StreamPeerUDS`: `src/gda/harness/gda_harness.gd:100,204`; `fcntl.flock`: `src/gda/daemon/discovery.py:128-135,160-171`. ADR-0021 leaves a Windows transport to a future decision. |
| Daemon engine lifecycle | Session detachment and cleanup rely on Unix sessions, process groups, and signals. No Windows-owned process tree mechanism is implemented. | `src/gda/commands/daemon.py:604`; `src/gda/daemon/session.py:412,628-642,672`. These paths are blocked by the current Windows gate, so this is a porting dependency rather than an observed orphan on Windows. |
| Windowed session preflight | Windows has a stub that returns usable without checking a desktop/display capability. | `src/gda/display.py:351-359`. It is unreachable while the live gate remains, but must be implemented before making Windows windowed support comparable with macOS. |
| Godot executable discovery | Without `--godot` or `GDA_GODOT`, Windows receives the same macOS `.app` executable default. There is no Windows default or PATH discovery. | `src/gda/binary.py:19,44`. Explicit configuration remains supported, so this is a setup/discovery gap, not a blocker for every headless operation. |
| CLI/MCP Unicode output | JSON emitted to a pipe uses the Python output encoding. On this native Windows host that encoding is GBK, while gda-mcp decodes the child output as UTF-8. Non-ASCII result values can be corrupted or output can fail after the requested filesystem mutation already succeeded. | Emission: `src/gda/headless.py:708` (failure JSON at line 685); MCP decode: `src/gda/mcp/runner.py:129-130`. Real `scene create --root-name 测试 --json` returned exit 0 and GBK bytes; UTF-8 decode produced four U+FFFD characters. A root name `😀` returned exit 1 with `UnicodeEncodeError`, while the `.tscn` was already created. Both names returned correct UTF-8 and exit 0 with `PYTHONUTF8=1`. |
| MCP roots on Windows | A `file:///D:/...` root is converted to `/D:/...`, not a native Windows drive path. UNC URI authority is also discarded because only `.path` is read. MCP can lose the advertised workspace and fall back to cwd or fail project resolution. | `src/gda/mcp/server.py:237-239`; root candidates are passed directly to `Path(root)` at `src/gda/mcp/project_context.py:65-68`. Native path probe for the existing checkout returned `exists=False` for the decoded drive URI path. `GDA_PROJECT` bypasses this root conversion. |
| MCP `GDA_BIN` override | POSIX shell splitting consumes backslashes in an unquoted native path or UNC executable path. | `src/gda/mcp/runner.py:71-73`. Actual `gda_command()` probe: `C:\tools\gda.exe` became `C:toolsgda.exe`; `\\server\share\gda.exe` became `\serversharegda.exe`. A double-quoted path preserved its backslashes in the same probe. The default `[sys.executable, '-m', 'gda']` avoids this defect. |
| Native exception status classification | The shared crash classifier recognizes only negative signal return codes. Windows exception-style status codes can escape crash classification. | `src/gda/errors.py:582-590`. A native child deliberately calling `ExitProcess(0xC0000005)` returned positive `3221225477`; feeding its actual `RunResult` into `classify_launch_or_crash` returned `None`. This confirms status handling, not an actual Godot crash. Sentinel operations can fall through to `operation_failed`; passthrough channels can expose the status as completed-run data. |

### Coverage and test-porting gaps

| Area | Existing evidence | Windows gap |
| --- | --- | --- |
| Root CI | The root unit/build job and Godot e2e job run on Ubuntu (`.github/workflows/ci.yml:145,197`). | No Windows or macOS CI matrix. README explicitly acknowledges untested Windows headless CI (`README.md:345`). |
| Engine provisioning | The composite action chooses `linux.x86_64`, uses Bash/chmod, and installs export templates below the Linux data directory (`.github/actions/install-godot/action.yml:22-24,46,62`). | A Windows CI runner needs an engine/template provisioning path before the current e2e job can be reused. |
| Artifact smoke | CLI documents macOS-only measured evidence (`src/gda/commands/export.py:1685-1687`; `README.md:461`). Its e2e module skips every host except Darwin (`tests/export/test_e2e_export_smoke.py:34-40`). | No Windows `.exe` smoke proof for argument forwarding, timeout capture, strict verdicts, diagnostics, or private `user://`. This is a declared verification/support gap; the source does not reject a runnable `.exe` by platform. |
| Harness exclusion in native exports | Host preset selection covers Linux and macOS only (`tests/harness/test_e2e_harness_install.py:228-239`). | Windows export cleanliness, native startup, and inert harness behavior are skipped. |
| Native Windows export | Shared export-run fixtures use a Linux/X11 preset (`tests/export/test_e2e_export_run.py:52-83`). | Passing these tests on Windows would prove cross-export behavior, not a native Windows build/run workflow. A Windows Desktop preset and `.exe` run evidence are needed. |
| User-data fixtures | `restricted_home` and `writable_home` call `engine_data_path` with only `HOME` (`tests/runtime/test_e2e_user_data.py:117-118,136-137`). | The production Windows branch requires `APPDATA` (`src/gda/runner.py:272-274`), so these fixtures return `None` and fail setup on Windows. Their child environment also redirects HOME (`tests/runtime/test_e2e_user_data.py:158`), which does not relocate the Windows data root. This is a fixture-porting defect, not evidence that the production APPDATA path fails. |
| Permission and symlink tests | Several tests use POSIX chmod or symlinks (for example `tests/project/test_e2e_project_create.py:262-305`, `tests/scene/test_e2e_scene.py:398-402`). | Classify real failures separately: Windows directory ACLs and symlink privileges differ from these fixtures. A failed setup must not be counted as a failed gda capability without a direct reproduction. |
| Live e2e | Live test modules explicitly skip non-POSIX hosts; for example `tests/daemon/test_e2e_daemon.py:125`, `tests/live/test_e2e_screen.py:48`, `tests/mcp/test_e2e_mcp_live.py:46`. | A green Windows run can coexist with all live functionality absent. Report skipped tests and reasons with the pass/fail count. |

### Existing Windows handling and remaining limits

There is already meaningful platform handling to preserve:

- `engine_data_path` and `data_path_env` read and relocate `APPDATA` on Windows (`src/gda/runner.py:272-274,296-297`).
- Engine output is captured as bytes and decoded as UTF-8 on reader threads, avoiding non-selectable Windows pipes and locale decoding (`src/gda/runner.py:624,924-928`). This fixes engine-to-gda capture, but does not fix gda-to-caller pipe encoding described above.
- Export template lookup uses the capitalized `Godot` directory on Windows and macOS (`src/gda/ops/groups/export.gd:190-197`).
- MCP invokes the paired interpreter by default and its real stdio test resolves a Windows `.exe` console launcher (`src/gda/mcp/runner.py:74`; `tests/mcp/test_e2e_mcp_stdio.py:38-44`).
- Skill install directories are constructed with portable paths and `~` expansion; no Windows-only install blocker was established by source inspection (`src/gda/skill_targets.py:52-61`).

One Windows semantic difference still needs behavioral evidence: the shared headless teardown calls `Popen.terminate()`, which ends a Windows process without the Unix SIGTERM-driven normal Godot shutdown (`src/gda/runner.py:1075-1089`). Therefore timeout or interruption evidence must not promise flushed exit-time diagnostics. Descendant ownership, native access-denied cases, junctions, UNC paths, and long-path behavior need targeted Windows tests after the main e2e results identify concrete failure paths.

### Console wrapper lifecycle: an inspected risk that did not reproduce

The configured Godot console executable is a wrapper, and the actual engine is a child executable. This fact alone does not prove an orphan defect. The available upstream source creates a Windows Job Object (`D:/project/godot/platform/windows/console_wrapper_windows.cpp:103`), sets `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (line 127), launches suspended and assigns the child to the job (lines 149-154), waits for the entire process tree (line 167), and returns the main child's exit code (line 178). That source checkout is revision `0eadbdb5d0709e4e557e52377fa075d3e2f0ad1f`, which is not the installed 4.6.3 binary revision; its behavior therefore needed a native probe.

The installed wrapper's SHA-256 is `63B3B2208819714C9677FBFDD8217C5B7DEE8ECF5F383502E826BC9E2227FF5A`. A corrected bounded isolated launch produced wrapper PID 50744 and engine child PID 59044. The script printed `WRAPPER_AUDIT_WEDGE` on stdout and stderr before entering an infinite loop; the probe waited for that marker (observed after 0.453 seconds). A handle to the exact child was opened, and `GetExitCodeProcess` confirmed `STILL_ACTIVE` (259) immediately before calling gda's real `_end_process` on the wrapper. After teardown, that same handle reported child exit status 0 and `still_active=false`; wrapper exit status was 1. This proves cleanup of this confirmed active, wedged child, not every timeout state or every Godot version. No orphan cleanup was necessary, and no other process was stopped. The earlier startup-only probe did not observe the wedge marker and is superseded by this readiness-checked probe.

## Reproducible native probes

Run these with this checkout's `.venv/Scripts/python.exe`. The actual native probe results are recorded in `docs/research/windows-platform-audit-2026-10-06-probes.json`. These are diagnostic probes, not additional e2e pass counts.

For Unicode output, create a fresh `project.godot` with `config_version=5` and the compatibility renderer, then use a raw-byte `subprocess.run(..., capture_output=True)` around:

```text
<repo-python> -m gda --user-data-root <private-data-dir> scene create res://probe.tscn --root-type Node --root-name 测试 --project <fresh-project> --json
```

Repeat with a new scene path, `--root-name 😀`, and with `PYTHONUTF8=1` in the child's environment. Set `GDA_GODOT` to the configured console executable. Unset `PYTHONIOENCODING` for the native-default arm. Decode the captured bytes explicitly with UTF-8 and GBK and compare; also check that the `.tscn` exists after a nonzero result. The observed `测试` bytes were `b2e2cad4` by default and `e6b58be8af95` with UTF-8 mode. The emoji arm failed only during JSON emission with default encoding.

The pure path and status probes are:

```python
from pathlib import Path
from urllib.parse import urlparse, unquote
import os, subprocess, sys
from gda.mcp.runner import gda_command
from gda.runner import RunResult
from gda.errors import classify_launch_or_crash

root = unquote(urlparse('file:///D:/project/godot-agent-worktree/gda-win-dev').path)
print(repr(root), Path(root).exists())  # '/D:/...', False
for override in [r'C:\tools\gda.exe', r'\\server\share\gda.exe']:
    os.environ['GDA_BIN'] = override
    print(repr(override), gda_command())
p = subprocess.run([sys.executable, '-c',
    'import ctypes; ctypes.windll.kernel32.ExitProcess(0xC0000005)'],
    capture_output=True)
print(p.returncode, classify_launch_or_crash(
    RunResult(stdout='', stderr='', exit_code=p.returncode), Path(sys.executable)))
```

The last child chooses an exception-style status explicitly; it does not crash Godot and must not be described as a reproduced engine crash.

For console-wrapper cleanup, create a fresh project with the compatibility renderer and a `SceneTree` script whose `_initialize()` prints and printerrs `WRAPPER_AUDIT_WEDGE` before `while true: OS.delay_msec(50)`. Launch the configured console executable with `--headless --path <private-project> --script res://wedge.gd --log-file <private-log>`, with private `APPDATA`. Drain both pipes concurrently and wait at most eight seconds for the wedge marker. Enumerate only children whose parent PID is this probe's wrapper PID using `CreateToolhelp32Snapshot`/`Process32FirstW`/`Process32NextW`. Open process handles for those identified children and confirm `GetExitCodeProcess == STILL_ACTIVE` immediately before calling `gda.runner._end_process(wrapper)`, then query those same handles again. A cleanup proof requires both observed readiness and active status before teardown. If a probe child remains active, clean only its pre-opened handle with `TerminateProcess`. This avoids a process-name kill and avoids confusing PID reuse with the original child.

## Recommended order

1. Fix and verify UTF-8 at the CLI pipe boundary, Windows MCP file-URI conversion, and the optional executable override. Include non-ASCII success and error payloads, and the case where a mutation succeeds before output fails. `PYTHONUTF8=1` is a verified temporary workaround for encoding.
2. Establish Windows native CI and host-specific fixtures before interpreting every suite failure as a product defect. Provide Windows engine/templates, native `.exe` export and smoke coverage, APPDATA fixtures, and ACL/symlink tests that exercise the intended contract. Count platform skips explicitly.
3. Define and implement Windows live-stack support across both transport legs, daemon discovery/liveness, permissions, process ownership, and display preflight. Update ADR-0021 and the published command constraints together. Passing a headless suite does not close the 24-command live/lifecycle gap.
4. Verify Windows exception-status classification and timeout/interruption diagnostics with an actual faulting engine or artifact after the basic headless/MCP paths are stable. Preserve the console wrapper's verified job ownership when deciding whether to launch the wrapper or engine directly.

## Native e2e execution

The full baseline ran on Windows 11 build 26200, Python 3.13.7, pytest 9.0.3, pytest-xdist 3.8.0, gda 0.22.0 (editable from the revision above), and Godot 4.6.3 official `7d41c59c4`. Python UTF-8 mode was off; its native locale/output encoding was cp936/GBK. `GDA_USER_DATA_ROOT` was unset. Export templates were absent; symlink creation returned WinError 1314. This audit did not run a macOS host: the macOS comparison is based on implementation, published constraints, and existing tests, not a same-revision macOS pass count.

Dependencies were installed from `uv.lock` with `uv sync --frozen --dev`. A first pytest startup failed before tests ran because its default temporary directory was not accessible. The baseline below uses a dedicated workspace temporary directory; that infrastructure startup failure is excluded from all test counts. Engine runs used the host environment outside the default sandbox. No production or existing test source was changed.

```powershell
$env:GDA_GODOT = 'D:/Godot_v4.6.3/Godot_v4.6.3-stable_win64_console.exe'
.venv/Scripts/python.exe -m pytest tests -m e2e -n 4 --dist loadgroup --basetemp=.audit-cache/e2e/native-tmp -ra --junitxml=.audit-cache/e2e/windows-native.xml
```

Collection selected 859 e2e cases from 3,951 root tests; 3,092 non-e2e cases were deselected. Baseline start: 2026-10-06 18:45:57 (Asia/Shanghai).

| Run | Selected | Passed | Failed assertions | Setup errors | Skipped | Pytest wall time |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Full native baseline, UTF-8 mode off | 859 | 655 | 48 | 32 | 124 | 572.39 s |
| UTF-8 diagnostic retry of the 80 failures/errors only | 80 | 19 | 28 | 32 | 1 | 24.94 s |
| Native-encoding control retry of 10 engine-failure cases | 10 | 9 | 0 | 0 | 1 | 21.54 s |

The native baseline pass rate is 76.3% of selected cases, or 89.1% of the 735 non-skipped cases (including setup errors in that denominator). The two retries are diagnostic subsets. They are not new full-suite results and must not be combined with the baseline to claim a full UTF-8 suite pass.

The baseline summary reports 29 warnings; its warning section contains 28 grouped `PytestUnhandledThreadExceptionWarning` blocks from subprocess reader threads failing to decode engine output as GBK. The native control reports one such warning; the UTF-8 diagnostic subset reports none. This is an additional test-capture portability gap, including in tests counted as passed. Shared direct engine import capture uses `text=True` without an explicit encoding (`tests/support.py:287-293`); the production engine runner already captures raw bytes and decodes UTF-8. A passing assertion does not recover the engine stream lost by a failed test reader.

The UTF-8 retry sets `$env:PYTHONUTF8 = "1"` and passes the node ids in `failed-nodes.txt`, with a fresh `--basetemp=.audit-cache/e2e/utf8-tmp`. The native control sets `PYTHONUTF8=0`, selects `native-control-nodes.txt`, and uses another fresh basetemp. All three runs use the same engine and four workers.

### Baseline by module

| Module | Total | Passed | Failed | Errors | Skipped |
| --- | ---: | ---: | ---: | ---: | ---: |
| asset_file | 12 | 11 | 1 | 0 | 0 |
| cli | 2 | 2 | 0 | 0 | 0 |
| daemon | 40 | 0 | 0 | 0 | 40 |
| export | 37 | 14 | 3 | 0 | 20 |
| harness | 4 | 2 | 1 | 1 | 0 |
| live | 70 | 0 | 1 | 15 | 54 |
| mcp | 10 | 0 | 8 | 0 | 2 |
| meta | 7 | 6 | 1 | 0 | 0 |
| node | 159 | 158 | 1 | 0 | 0 |
| project | 164 | 137 | 14 | 7 | 6 |
| resource | 46 | 43 | 3 | 0 | 0 |
| runtime | 33 | 26 | 0 | 6 | 1 |
| scene | 111 | 106 | 5 | 0 | 0 |
| script | 126 | 116 | 10 | 0 | 0 |
| value_projection | 38 | 34 | 0 | 3 | 1 |
| **Total** | **859** | **655** | **48** | **32** | **124** |

### Failure and error classification

These counts describe failed test observations, not a count of distinct product defects. Each original failure/error is assigned once. Per-case details and retry status are in `results.json`.

| Baseline cause or evidence category | Cases | Interpretation |
| --- | ---: | --- |
| MCP startup blocked by schema output encoding | 8 | Confirmed product defect. GBK cannot encode the `UID↔path` description (`src/gda/commands/resource.py:231`); `gda schema` raises at `src/gda/commands/meta.py:576`, with exit 1 and empty stdout. Independent UTF-8 probe returns parseable JSON. Seven MCP tests pass with UTF-8; roots routing still fails separately. |
| CLI Unicode output failure | 2 | Confirmed product encoding defect, consistent with the real Chinese/emoji mutation probes. Both Unicode-space tests pass with UTF-8. |
| Engine verdict not reproduced on retry | 11 | Ten direct opaque nonzero exits, plus one aliased-scene comparison containing an engine failure. UTF-8 retry: ten pass, one reaches the missing-template skip. The native control reruns nine direct cases successfully and skips the template case. Three representative raw operations each pass three times under native encoding. Root cause remains unknown; do not attribute these to an encoding fix or declare them resolved. |
| Equivalent path spellings compared as strings | 9 | Test portability: slash/backslash or mixed-separator spelling, while the operation returns the expected semantic result. Examples: project-create `project_file`, missing-binary message, nested owner path, export-template root, and reported user-data path. |
| Symlink privilege unavailable | 14 | Seven test-body failures plus seven setup errors, WinError 1314. The affected product behavior was not reached. No system privilege or Developer Mode setting was changed. |
| Windows-invalid filenames in fixtures | 3 | Two sentinel filenames contain `<`/`>`; one uses `outside:`. These fixtures cannot represent the POSIX filename scenario on Windows. |
| POSIX chmod assumptions | 2 | The intended unreadable/unwritable restriction is not established by those mode bits on Windows; successful I/O is not proof of a gda permission defect. |
| UNIX-only capability expected on Windows | 2 | Tests expect daemon install or `daemon_not_running`, but the correct current product response is `live_unsupported_platform`. |
| POSIX daemon runtime fixture | 19 | Setup uses `tempfile.mkdtemp(dir="/tmp")`; failure occurs before the unsupported live path is exercised. These missing Windows guards are test defects. |
| POSIX /tmp working directory | 2 | CLI subprocess cannot start with nonexistent Windows `cwd="/tmp"`. |
| HOME-only user-data fixture | 6 | Setup passes HOME without APPDATA and fails before engine execution. |
| Unescaped Windows path in Theme probe | 1 | The test inserts backslashes into a GDScript string. A corrected, separate probe using a forward-slash path loads the same gda-created file as Theme and exits 0. |
| CRLF normalized by spill test | 1 | `Path.read_text()` changes CRLF to LF before the test recounts bytes. The difference is 3,003 bytes: 174,091 vs 177,094. This assertion does not establish lost output; use raw bytes for the Windows byte-count check. |
| **Total** | **80** | **48 failures + 32 setup errors** |

The UTF-8 roots test gives real product evidence beyond the path probe: it reports success but writes `from_roots.tscn` in the repository cwd instead of the advertised project. The generated file was moved into this audit evidence directory; no such test artifact remains in the repository root. Explicit `GDA_PROJECT` routing passes with UTF-8.

### Baseline skips

| Reason | Cases |
| --- | ---: |
| UNIX-only daemon/live paths (96 named AF_UNIX skips, one POSIX condition) | 97 |
| Artifact smoke e2e evidence restricted to macOS | 15 |
| Export templates absent | 4 |
| Linux-only XDG template test | 1 |
| POSIX directory permission mode cannot establish the restriction | 6 |
| User-data root has a flat layout rather than the tested nested layout | 1 |
| **Total** | **124** |

No real Windows Desktop export followed by native `.exe` smoke was verified. The successful-export/harness fixtures lack a Windows host target, and templates were not installed. Skips remain coverage gaps rather than passing capabilities.

### Evidence and follow-up

Raw baseline [JUnit](windows-platform-audit-2026-10-06/windows-native.xml) and [log](windows-platform-audit-2026-10-06/windows-native.log); diagnostic [UTF-8 JUnit](windows-platform-audit-2026-10-06/windows-utf8-retry.xml) and [native-control JUnit](windows-platform-audit-2026-10-06/windows-native-control.xml); [all case results and classifications](windows-platform-audit-2026-10-06/results.json). [Native/schema probes](windows-platform-audit-2026-10-06/raw-op-probe.json), [Theme probe](windows-platform-audit-2026-10-06/theme-probe.json), [command inventory](windows-platform-audit-2026-10-06-commands.json), and [platform/Unicode/wrapper probes](windows-platform-audit-2026-10-06-probes.json) are separate from e2e totals.

Existing tracking: [#1077, Project scan: unverified cost and platform behavior](https://github.com/aigengame/godot-agent/issues/1077) already records absent Windows evidence for project scan. This audit adds Windows test evidence but does not verify that issue's large-project cost or older-engine items. No external issue or comment was published.

Ready follow-up scopes: (1) establish UTF-8 for all CLI output and unblock MCP schema startup; (2) convert Windows drive/UNC file URIs and preserve executable overrides, with a roots write reaching only its advertised project; (3) port the e2e fixtures and add a Windows CI engine/template job; (4) add Windows Desktop export and artifact smoke evidence; (5) design Windows live transport/liveness/process/display support and amend ADR-0021; (6) capture Windows exception statuses correctly and retain raw status evidence for the unreproduced engine exits.

The production source remains unchanged. The observed suite is not green, the 24-command capability gap remains, and the unreproduced engine failures remain open.
