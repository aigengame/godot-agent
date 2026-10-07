# Windows UTF-8 entry verification (#1110)

Source under test: `62df1e3f8fabdf1894b8bdb44c5fae53dbfee335`, based on
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
.venv/Scripts/python.exe -m pytest tests/cli/test_entry_stdio.py tests/mcp/test_entry_stdio.py tests/mcp/test_e2e_mcp_stdio.py tests/mcp/test_mcp_stdio_handshake.py tests/cli/test_e2e_params_json.py -q -p no:cacheprovider --basetemp .audit-cache/1110-evidence --junitxml docs/research/windows-utf8-entry-2026-10-07/results.xml --tb=short
```

The [raw JUnit result](results.xml) records 29 passed, 0 failed, 0 errors and
0 skipped: 16 real-engine cases and 13 engine-free real-entry cases. Coverage
includes both CLI launch forms, help and early errors, schema discovery, MCP
protocol eras, Chinese/emoji stdin and successful scene mutation/read-back,
Unicode structured failures, and raw spill bytes/counts with native CRLF.

Related Windows fast regression selection: 228 passed, 7 failed. All seven
also fail using the integration source: four params tests assume Unix paths or
`~user` semantics, two provenance tests assume Unix `chmod`, and one assumes a
Unix binary path. The separate launch suite has the same 19 failures / 4 passes
on both revisions (Unix executable fixtures and path spelling). These remain
within [#1113](https://github.com/aigengame/godot-agent/issues/1113).

The source's Ruff check/format and pyright with this interpreter and
`--pythonplatform Linux` pass. Actual Unix PR checks are reported by GitHub;
this local record establishes Windows evidence only. Historical results are
frozen; later verification uses its own tested revision.
