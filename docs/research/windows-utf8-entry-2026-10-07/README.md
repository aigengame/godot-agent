# Windows UTF-8 entry verification (#1110)

Primary source under test: `62df1e3f8fabdf1894b8bdb44c5fae53dbfee335`, based on
integration `ebf7297507b7293c137c1bd2530a2685e49e2b01`.

Host: Windows 11 build 26200, Python 3.13.7, Godot 4.6.3 console binary.
Before entry, Python UTF-8 mode is **0**, locale is `cp936`, and all three
standard streams report `gbk`. No suite-wide UTF-8 environment switch was used.
New entry tests set `PYTHONUTF8=0` per child, either remove `PYTHONIOENCODING`
(native caller), or set it to `cp1252` (also falsifiable on Unix). Both installed
console scripts belong to this checkout's environment, refreshed by
`uv sync --frozen --dev --package gda`.

Run from the checkout in PowerShell, replacing the Godot path:

```powershell
$env:GDA_GODOT = '<Godot 4.6.3 console executable>'
.venv/Scripts/python.exe -m pytest tests/cli/test_entry_stdio.py tests/mcp/test_entry_stdio.py tests/mcp/test_e2e_mcp_stdio.py tests/mcp/test_mcp_stdio_handshake.py tests/cli/test_e2e_params_json.py -q -p no:cacheprovider --basetemp .audit-cache/1110-evidence --junitxml .audit-cache/1110-evidence.xml --tb=short
```

The raw JUnit result records 29 passed, 0 failed, 0 errors and
0 skipped: 16 real-engine cases and 13 engine-free real-entry cases. Coverage
includes both CLI launch forms, help and early errors, schema discovery, MCP
protocol eras, Chinese/emoji stdin and successful scene mutation/read-back,
Unicode structured failures, and raw spill bytes/counts with native CRLF.

## Auxiliary regression receipts

Re-captured at `4c1d88c0efebc41acacd87ed3a54559e246f9b69`, against the same
integration base. The primary receipt above remains unchanged. All auxiliary
runs use the same native host, interpreter and locked dependencies, with no
`PYTHONUTF8` or `PYTHONIOENCODING` environment override. The baseline imports
archived Python source; the three comparison test files are identical between
base and head. This is a source/fixture comparison, not a baseline console install.
The environment and checks receipt (`checks.log`) records both actual import
locations, UTF-8 mode 0, native locale/stdio, and static-check commands/exit codes.

| Selection / source | Selected | Passed | Failed | Errors | Skipped | Raw JUnit |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Related fast / head | 235 | 228 | 7 | 0 | 0 | `head-fast.xml.gz` |
| Launch / head | 23 | 4 | 19 | 0 | 0 | `head-launch.xml.gz` |
| Params, provenance, launch / base | 172 | 146 | 26 | 0 | 0 | `base-comparison.xml.gz` |

The fast selection deselects 10 real-engine cases; the other two selections
deselect none. Each pytest process exits 1 because the recorded failures remain.
The base receipt contains params **103/4**, provenance **39/3**, and launch
**4/19** passed/failed cases. Its 26 failing test IDs equal the union of the
head's 7 fast failures and 19 launch failures. Failure messages and the unchanged
fixtures expose the Unix path/`~user` assumptions, Unix `chmod` expectations,
and shebang/shell stand-ins that do not launch on this Windows host. These
remain within [#1113](https://github.com/aigengame/godot-agent/issues/1113);
the auxiliary selections are not reported as green Windows suites.

Recorded commands, from the tested checkout in PowerShell (use fresh output
paths for a later run):

```powershell
$records = 'docs/research/windows-utf8-entry-2026-10-07'
$fast = @(
    'tests/cli/test_entry_stdio.py', 'tests/mcp/test_entry_stdio.py',
    'tests/cli/test_unknown_invocation.py', 'tests/cli/test_parser.py',
    'tests/cli/test_params_json.py', 'tests/meta/test_cli_version.py',
    'tests/repo/test_import_direction.py', 'tests/meta/test_version_provenance.py',
    'tests/meta/test_schema_aggregate.py', 'tests/mcp/test_mcp_runner.py',
    'tests/mcp/test_mcp_packaging.py', 'tests/mcp/test_mcp_stdio_handshake.py'
)
.venv/Scripts/python.exe -m pytest @fast -m 'not e2e' -q -p no:cacheprovider --basetemp .audit-cache/1110-review-head-fast --tb=short --junitxml "$records/head-fast.xml"
.venv/Scripts/python.exe -m pytest tests/runtime/test_launch.py -q -p no:cacheprovider --basetemp .audit-cache/1110-review-head-launch --tb=short --junitxml "$records/head-launch.xml"

git archive --format=zip --output=.audit-cache/1110-review-base.zip ebf7297507b7293c137c1bd2530a2685e49e2b01 src
Expand-Archive -LiteralPath .audit-cache/1110-review-base.zip -DestinationPath .audit-cache/1110-review-base
git diff ebf7297507b7293c137c1bd2530a2685e49e2b01 4c1d88c0efebc41acacd87ed3a54559e246f9b69 -- tests/cli/test_params_json.py tests/meta/test_version_provenance.py tests/runtime/test_launch.py
$env:PYTHONPATH = Join-Path (Get-Location) '.audit-cache/1110-review-base/src'
.venv/Scripts/python.exe -m pytest tests/cli/test_params_json.py tests/meta/test_version_provenance.py tests/runtime/test_launch.py -q -p no:cacheprovider --basetemp .audit-cache/1110-review-base-comparison --tb=short --junitxml "$records/base-comparison.xml"
Remove-Item Env:\PYTHONPATH

.venv/Scripts/ruff.exe check .
.venv/Scripts/ruff.exe format --check .
.venv/Scripts/pyright.exe --pythonpath .venv/Scripts/python.exe --pythonplatform Linux
```

The result files named in this record are not in the repository; they stay in
the workspace that produced them.

Ruff check/format and pyright with this interpreter and `--pythonplatform Linux`
exit 0 in `checks.log`. This type-check configuration follows the
existing Linux CI; it does not claim a full Windows type-check pass. Actual Unix
PR checks are reported by GitHub. This local record establishes Windows evidence
only. Historical raw results are frozen; later verification uses its own tested
revision and result files.
