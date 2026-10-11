# Windows MCP file-root verification (#1111)

Frozen verification at implementation/test revision
`882c7cfe6c17e619e312803e35b1c470074a9d5b`, based on integration
`4fd6ae55da09fdc5cdc05d6ef9b95e01dfe15f7e` (#1129). Scope and acceptance remain
in [#1111](https://github.com/aigengame/godot-agent/issues/1111).

## Native Windows result

Windows 11 build 26200, Python 3.13.7, MCP 2.0.0 and Godot 4.6.3 console;
exact package versions, paths, encoding controls and static results are in
`checks.log`. The result files named in this record are not in the repository;
they stay in the workspace that produced them. No `PYTHONUTF8`, `PYTHONIOENCODING`, `GDA_BIN` or
`GDA_PROJECT` workaround was set for the suite. Tests own their explicit project
pins and pass the console engine to subprocesses.

From the checkout root, PowerShell:

```powershell
$env:GDA_GODOT = 'D:\Godot_v4.6.3\Godot_v4.6.3-stable_win64_console.exe'
.venv/Scripts/python.exe -m pytest tests/mcp tests/repo/test_import_direction.py -q -rs -p no:cacheprovider --basetemp .audit-cache/1111-native --junitxml .audit-cache/1111-native.xml
```

`native.xml.gz`: **78 selected, 75 passed, 1 failed, 2 skipped**;
zero setup errors. This is a bounded MCP/import-direction run, not a full Windows
parity claim. The two skips are the existing Live MCP tests (`daemon uses AF_UNIX`).

- Both `test_file_roots_over_stdio_respect_project_precedence` cases passed.
  A real MCP client launches this checkout's `gda-mcp.exe` over stdio, which
  invokes the public `python -m gda` CLI and a real Godot engine. The advertised
  drive directory includes spaces, `%`, `#` and `café`. Scene creation lands only
  in that project, or in the explicit `GDA_PROJECT` when pinned; invoking cwd and
  the other unselected project retain their file contents.
- `test_mcp_file_roots.py`: 3 passed. Unusable roots are skipped individually,
  preserving later-root/cwd resolution. The native Windows UNC case preserves
  `\\server\share\My Game#%` through the real MCP session to the runner seam;
  only filesystem existence is faked. **No mounted-share engine run was made.**
- The sole failure is the unchanged
  `test_an_unresolvable_home_in_gda_project_still_resolves_a_literal_project`:
  Windows home expansion does not have the Unix unknown-user behavior assumed
  by the fixture. Baseline comparison below reproduces the same failure;
  portable fixtures belong to #1113.

## Baseline control

Prepare the isolated base without modifying the working tree:

```powershell
git archive --format=zip --output=.audit-cache/1111-base.zip 4fd6ae55da09fdc5cdc05d6ef9b95e01dfe15f7e src/gda tests/mcp/test_mcp_project_context.py tests/mcp_support.py tests/support.py tests/conftest.py pyproject.toml
.venv/Scripts/python.exe -c "from zipfile import ZipFile; ZipFile('.audit-cache/1111-base.zip').extractall('.audit-cache/1111-base')"
Push-Location .audit-cache/1111-base
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
& '<checkout>\.venv\Scripts\python.exe' -m pytest tests/mcp/test_mcp_project_context.py -q -p no:cacheprovider --basetemp ../1111-base-temp --junitxml ../1111-base.xml
Remove-Item Env:PYTHONPATH
Pop-Location
```

`base.xml.gz`: **9 selected, 8 passed, 1 failed**; zero skips/errors.
The resolver and this test file have identical source text at base/head (see
checks.log); the archived source takes precedence via this command's `PYTHONPATH`.

Intermediate red/green runs stay in local cache; routine CI checks are linked
below.

## Unix regression

The existing Linux workflow was dispatched at the exact implementation/test
revision with `gh workflow run ci.yml --ref codex/1111-mcp-file-roots -f run-e2e=true`:
[run 37582260832](https://github.com/aigengame/godot-agent/actions/runs/37582260832).
The workflow passed: **830 gda e2e tests passed, 41 skipped** (871 selected).
Skip reasons: 25 windowed-session cases on a host without a display, 15
macOS-only export-evidence cases and 1 nested user-data test on flat XDG paths.
The unmodified example game's engine tier passed 66 tests, skipped 3 for
windowed-session unavailability and deselected 485. Its job logs own commands,
environment and raw results.

[PR CI at c33d0ed0](https://github.com/aigengame/godot-agent/actions/runs/37583658657)
passed: 3107 unit tests, 4 skipped; 480 example pure-Python tests passed;
lint, type check and package build passed. Later changes since the pinned
implementation/test revision only adjust documentation. Windows CI remains excluded.
