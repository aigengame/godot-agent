# Native Windows symlink validation

Follow-up receipt for [#1182](https://github.com/aigengame/godot-agent/issues/1182).
Tested revision: `43d973b4ccf1e5193a48d6819d61cbbe7cb93022` on Windows 11
build 26200, Python 3.13.7 / pytest 9.0.3, and explicitly configured Godot
`4.6.3.stable.official.7d41c59c4` Windows console executable.
The relevant tests, helpers and product path owners are unchanged from PR
#1180's reviewed head `506fb0652d290d925c53ef42f5d751be0cc6b7ae`.

## Execution context and 12 existing cases

The ordinary process lacks `SeCreateSymbolicLinkPrivilege`: file and directory
creation each returned WinError 1314, and the selection recorded **0 passed /
12 skipped / 0 failed / 0 errors**. The maintainer then authorized one temporary
administrator validation process through UAC. No Developer Mode, registry or
system permission policy was changed; the temporary process exited afterward.

In that context, file and directory symlinks had actual reparse tag
`0xa000000c`, and reads through both matched their targets. The existing
`unlistable` fixture produced directory-list denial and restored access.
The same 12 cases reached their original assertions: **12 passed / 0 skipped /
0 failed / 0 errors**. No invocation-wide home, user-data-root or encoding mask
was supplied. These are fast-test results, not complete real-Godot e2e evidence.

Exact selection and command (PowerShell; local output paths redacted):

```powershell
$scratch = '<writable-scratch>'
$cases = @(
  'tests/export/test_export_smoke_operation.py::test_a_symlink_to_a_runnable_file_is_runnable'
  'tests/export/test_export_smoke_operation.py::test_a_broken_symlink_is_not_found'
  'tests/export/test_export_tree_mutations.py::test_an_unreadable_file_is_named_in_the_render'
  'tests/project/test_project.py::test_a_file_symlinked_into_the_project_is_inside'
  'tests/project/test_project.py::test_the_reissue_target_is_lexical_so_a_file_link_still_has_one'
  'tests/project_tree/test_project_tree_inventory.py::test_a_link_that_leads_back_up_the_chain_is_not_re_entered'
  'tests/project_tree/test_project_tree_inventory.py::test_a_file_the_walk_cannot_read_is_skipped_not_failed'
  'tests/project_tree/test_project_tree_inventory.py::test_a_spelling_that_vanishes_between_the_captures_does_not_split_one_inode'
  'tests/project_tree/test_project_tree_inventory.py::test_a_spelling_retargeted_to_a_second_unreadable_inode_counts_both'
  'tests/resource/test_resource_import_commands.py::test_a_symlink_cycle_under_the_project_terminates'
  'tests/resource/test_resource_import_commands.py::test_relative_project_with_symlinked_asset_is_structured'
  'tests/resource/test_resource_import_commands.py::test_symlinked_in_asset_is_accepted_like_the_engine_walks_it'
)
uv run --frozen pytest -q -rs -p no:cacheprovider @cases "--basetemp=$scratch/pytest" "--junitxml=$scratch/results.xml"
```

## Real-engine target observations

Temporary projects use `tests.conftest.project_godot`, with file logging
disabled at the fixture source. Both layouts were measured with actual
directory symlinks in the authorized context, then independently with junctions
in the ordinary context (`0xa0000003`). Python resolution was recorded, but the
target conclusions below come from Godot reads and actual command results.

The project-side script contains `const WITNESS = "inside-project"`; the
external script contains the distinct, invalid declaration
`const WITNESS: int = "outside-target"`. PNGs made by the existing e2e `_png`
helper are red inside (`ff0000`) and blue outside (`0000ff`). A direct-engine
control reads the raw script spelling through `FileAccess.get_file_as_string`
and the PNG through `Image.load`. After a successful import it also reads the
loaded texture's first pixel, so the imported content is observed separately.

| Layout and input | `script validate` | `resource import` | Godot target observation |
| --- | --- | --- | --- |
| `game/pivot -> outside/deep`; `pivot/../deck.gd` and `pivot/../deck.png` | Exit 0, `valid=true`; reported path `pivot\..\deck.gd` | Exit 0, `engine_pass=true`, `status=imported`; mapped to `res://deck.png` | Reads `game/deck.gd` and red `game/deck.png`; imported texture is red. Only the inside target gets a sidecar. |
| `game/addons/plain -> libs/plain`; `addons/plain/../shared.gd` and `.png`; inside files stored as `Shared.gd` / `Shared.png` | Exit 4, `path_case_mismatch`, before engine launch | Exit 4, `path_case_mismatch`, before engine launch | Isolated direct-engine control reads the inside `Shared.gd` and red `Shared.png`. Neither target gets an import sidecar. |

The second layout's refusal coordinates are `requested_path`:
`res://addons/shared.gd`, `stored_path`: `res://addons/Shared.gd`; the import
route reports the corresponding `.png` pair. The external library has no
project marker. Containment therefore admits the native inside target, and the
spelling gate diagnoses its case. The control does not modify or bypass gda's
gate in the product invocation.

Public commands for each layout, with the engine and project paths supplied
explicitly; machine-specific paths are represented by placeholders:

```text
python -m gda script validate <relative-script> --project <game> --godot <console.exe> --json
python -m gda resource import <relative-png> --project <game> --godot <console.exe> --json
<console.exe> --headless --path <game> --script <temporary-observe.gd> --log-file <scratch-log>
```

Real-symlink and junction observations agree for these two measured layouts.
No gate/engine target mismatch was observed. This does not establish general
link equivalence, behavior on other versions/filesystems, or full platform
parity. Keep the two original POSIX tests' Windows skips and the six unrelated
filename/execute-bit exclusions. Product code, tests, helpers and CI are
unchanged. Raw JUnit, logs and temporary probes remain local; this compact
receipt is the only retained artifact.
