---
status: accepted
---

# The editor context: a one-shot headless editor runs a gda payload

gda serves two Godot execution contexts: the runtime `--script` context of a
[Headless operation](../../CONTEXT.md), and the running game of a
[Live operation](../../CONTEXT.md). The engine has a third: the editor, which writes its
own state (the class index, the import cache, UIDs) and applies its own semantics.
ADR-0017 kept the editor out of scope, and ADR-0032 rejected an `--editor` launch shape.
gda reaches the editor's state today only through the engine import pass
(`--import`), and reads the result back through a second engine or through ports of
engine rules.

Measurements on 2026-10-31 (Godot 4.4.1, 4.5.2 and 4.6.3 on macOS; gda at main
`9e41e0388`) show that a one-shot headless editor can host a gda payload with no window
and no plugin installed in the project. This record decides the **editor context**, in
which a gda payload runs in a one-shot headless editor: how gda hosts it, which commands
move to it first, and the rules for later growth. The project
owner accepted it on 2026-10-31 in
[#1252](https://github.com/aigengame/godot-agent/issues/1252). **Acceptance is not
delivery:** no command uses the editor context until its slice lands. Engine paths are at
`4.6.3-stable`.

## Context

### What the runtime context cannot reach

- **The class index.** Only an editor filesystem scan writes
  `.godot/global_script_class_cache.cfg`, and every other engine reads it once, at
  startup (CONTEXT.md, `Project scan`). `gda project scan` therefore runs the import pass
  and then starts a second engine to read the class list.
- **The import cache.** Only an import pass writes `.godot/imported/` and the `.import`
  sidecars. `gda resource import` runs the pass, then settles each asset by re-reading its
  artifacts with `Import evidence`, gda's port of `EditorFileSystem::_test_for_reimport`.
- **UIDs.** `ResourceSaver` writes a new `uid` only in the editor, which is why ADR-0036
  ratifies path-only references.
- **Editor instancing.** In the editor, a non-tool script gets a placeholder instance and
  its `_init` does not run. `node add --type` in the runtime context runs `_init` and
  stores what it set as an override (measured: `hp = 99`).

Both commands reach the pass through the `import_pass` [Shared step](../../CONTEXT.md)
(#1079), which has no other consumer.

### What was measured

- **Host.** `godot --headless -e --path <project> --script <payload>` boots the editor
  under the payload's SceneTree on 4.4.1, 4.5.2 and 4.6.3. The payload is ready when
  `EditorFileSystem.is_scanning()` is false after the first frames. It is not ready at
  `_initialize`. Output from `print()` reaches stdout.

  > **Outcome (2026-10-31, #1255):** at exit, this launch prints 5 leak lines of the
  > form `ERROR: <n> RID allocations of type '<name>' were leaked at exit.` and 3
  > `WARNING:` leak lines on stderr (4.6.3, macOS). The lines and their counts were the
  > same on the four projects measured, and CI's 4.6.0 run printed the same 5 `ERROR:`
  > lines. `-e --quit`, and `--script` without `-e`, print none (4.6.3, macOS). The
  > `ERROR:` lines come from `print_error`: they go to stderr on 4.6.0 (CI, Linux and
  > Windows) and to stdout on 4.6.3, where engine commit `6649bc1eb0` sends `print_error`
  > to stdout during cleanup. `project scan` reports the stderr lines in
  > `shutdown_leaks`, apart from `engine_errors`.
- **Cost** (4.6.3, warm project): about 2.3–2.8 s and 0.95 GB RSS per call, against
  0.2–0.3 s and about 115 MB for a runtime-context operation. A new private editor data
  root adds about 0.3 s on average (2.47–2.85 s with a new root against 2.27–2.47 s with
  a reused one, n=4). No scene was reopened in these runs.
- **A payload runtime error does not end the process.** The editor keeps running until it
  is killed.

  > **Outcome (2026-10-31, #1255):** this holds for a payload that calls `quit()` in the
  > function that fails. `editor.gd` keeps the single quit of `operations.gd` (#31): the
  > operation runs in one frame, and the next frame prints the result and quits. A
  > runtime error stops only its frame, so the editor exits 1 on the next frame
  > (`operation_failed`; 2.47 s on 4.6.3, macOS). A parse error in the payload exits 0
  > with no sentinel (`contract_violation`; 0.21 s). The timeout stays the bound for an
  > editor that does not quit. The same limit applies to "the timeout is also the bound
  > for that case" in decision 1 and to "A payload error waits for the timeout" in the
  > consequences.
- **The boot scan does the import pass's work.** On a project that was never opened, the
  boot scan writes the class index, and `ProjectSettings.get_global_class_list()` in the
  same process lists the project's classes. It imports every missing or stale asset of
  the project, as `--import` does: 301 assets on a cold boot of a synthetic project, 0 on
  a warm boot. `EditorFileSystem.resources_reimported` lists what it imported, and
  `EditorFileSystemDirectory.get_file_import_is_valid` marks an asset that failed to
  import (a corrupt PNG) on both boots. `update_file` on a new or renamed script updates
  the in-process class list and the index on disk.
- **Dialogs do not block.** An enabled editor plugin that fails to load opens an
  `AcceptDialog`, and the scan still completes. A corrupt asset opens no dialog.
- **Execution surface.** `@tool` scripts, `@tool` autoloads and enabled editor plugins
  run. Plain autoloads do not: a plain autoload's `_init` did not run on a boot.
  `.new()` on a non-tool script still runs `_init`.
- **Reopened scenes.** After the first scan, the editor reopens the scenes that the
  project's editor layout (`.godot/editor/editor_layout.cfg`) lists, because
  `interface/scene_tabs/restore_scenes_on_load` is on by default, and the `@tool` scripts
  in those scenes run (`EditorNode::_sources_changed`, `_load_editor_layout`). Measured
  with one scene: a `@tool` node's `_ready` ran, and a plain script's `_init` did not.
  `--import` reopened the same scene, and the native export boots the same editor
  (engine source; not measured on the export). A project that was never opened in the
  editor has no layout file.
- **The editor writes its environment.** Measured with an isolated `HOME` and `--import`:
  every boot rewrites `editor_settings-4.6.tres` in the platform's Godot config
  directory. Every editor boot also creates `app_userdata/<project>/.recovery_mode_lock`,
  and only a successful exit or the editor's timer after the first scan removes it
  (`main/main.cpp` L2176, L5151; `editor/editor_node.cpp` L1471). A boot that is killed,
  or that fails before the timer, therefore leaves it: measured on a killed boot and on a
  failed `--export-pack`. Project Manager reads that file and offers recovery mode
  (`editor/project_manager/project_list.cpp`, L735-L736); only `--recovery-mode` starts
  the editor in it. This was not reproduced through gda.
- **Platform directories** (engine source): the editor's data, config and cache
  directories come from `HOME` on macOS; from `XDG_DATA_HOME`, `XDG_CONFIG_HOME` and
  `XDG_CACHE_HOME` on Linux; and from `APPDATA` (data and config) and `LOCALAPPDATA`
  (cache) on Windows (`platform/*/os_*`, `editor/file_system/editor_paths.cpp`). Today's
  `User-data placement`, when a root is given, sets one variable: `HOME` on macOS, which
  moves all three; `XDG_DATA_HOME` on Linux, which leaves config and cache; and `APPDATA`
  on Windows, which leaves the cache.
- **UI language.** On a host whose OS language is `zh-Hans`, a fresh root shows the
  editor in Chinese. `--language en` makes it English.
- **Versions.** `EditorSettings.get_shortcut` is bound from 4.6 only. CI installs
  `4.6-stable` only; the measurements above that name no version are on 4.6.3.

## Decision

### 1. One host: a one-shot headless editor under a gda payload

An editor-context command is fulfilled by one [Headless launch](../../CONTEXT.md) with
the argument tail `-e --language en --path <project> --script <gda editor payload>`. The
payload is an entry script of its own, beside `operations.gd`. It waits until the
editor's filesystem scan ends, performs the operation through the editor API, prints the
result under the ADR-0002 sentinel, and quits. Nothing is installed in the project and no
window opens.

The editor context is an execution context of a Headless operation. It is not a third
operation class and not a delivery phase: the process is one-shot and needs no
pre-existing engine state. A new `ExecutionKind` value, `editor`, marks its commands, and
`--schema` publishes it. Each command belongs to exactly one context, and no call falls
back from one context to another. The engine import pass and the native export also boot
the editor, but they run no gda payload and are not the editor context.

The launch timeout bounds every call, and a timeout is `launch_timeout`, as on every
Headless launch. Because a payload error does not end the process, the timeout is also
the bound for that case.

### 2. Each call owns its editor environment

- Each editor-context call creates a private editor data root (the root) and attempts to
  remove it after every outcome, as Artifact smoke does (ADR-0042). A cleanup failure does
  not change the outcome.
- The launch points every platform directory that the editor writes into that root: the
  variables listed under Context, per platform. This applies to the editor context only;
  the other channels keep today's placement.
- Editor settings, the recovery-mode lock, the editor's `user://` and its caches are
  therefore written to the root and removed with it. The user's real Godot directories are
  not touched.
- `--user-data-root` (and `GDA_USER_DATA_ROOT`) stays the only override. When it is
  given, the caller's root replaces the private one, receives all the directories, and is
  kept. A caller can reuse it across calls to save the cost of a new root.
- `--language en` pins the editor UI language, so the editor's own text in a dialog
  disclosure does not follow the host's OS language.
- Not covered: a self-contained editor build (a `._sc_` or `_sc_` file beside the
  executable) keeps its data beside the executable, and no variable reaches it
  (`editor_paths.cpp`).

### 3. No lock

gda takes no lock for an editor-context call, as it takes none for any other Headless
operation. Two gda calls that write one project at the same time are not defended, and a
[Concurrent external editor](../../CONTEXT.md) stays undefended (ADR-0018). A persistent
editor session, if one comes, gets its single-writer rule from the session model
(ADR-0020).

### 4. Postconditions decide; dialogs are disclosure

- Each editor-context operation decides its result from an engine fact that it reads
  after it acts. Many editor API calls return nothing, so the absence of an error is not
  evidence.
- A visible dialog is not a verdict. After the operation acts, the payload reads the
  visible dialogs once and prints the class, title and text of each to its stderr, which
  reaches the caller under ADR-0002's child-stderr rule (#803). No result field and no
  error code are added for it. Reading a dialog does not act on it, so it is not route 3
  (decision 7).
- An unmet postcondition fails with the operation's existing failure. A later operation
  that must treat a dialog as its verdict declares that itself.

### 5. First scope: `project scan` and `resource import`

- **`project scan`.** One editor-context launch replaces the import pass and the second
  engine. The payload waits for the boot scan, which writes the class index, and reads
  the class list in the same process. The result shape does not change.
- **`resource import`.** `Import evidence` still decides before any spawn whether an
  engine is needed, so a fully cached request starts no engine, and the dry run does not
  change. When an engine is needed, the editor-context launch replaces the import pass.
  The boot scan imports what is missing or stale across the project, as the pass did: the
  editor context does not make the import per file. The settlement takes from the engine,
  in the same process, whether it imported each requested asset (`resources_reimported`,
  `get_file_import_is_valid`), instead of re-reading the asset's artifacts with gda's
  port. The other facts keep their roles: the pre-pass `reason` of #853 still explains a
  failed asset, and an asset that the engine did not import and that has no `.import`
  sidecar after the spawn is still `not_importable`. The statuses, the reasons and
  `engine_output` do not change. `engine_output` takes only the engine's lines: a line
  with gda's diagnostic prefix, such as a dialog disclosure (decision 4), is not one. The
  slice names the fact that decides each status.
- After both commands move, the `import` kind and the `import_pass` step have no
  consumer. The `resource import` slice deletes them.
- **Not moved now:** editor-way instancing for `node add --type` and `resource create
  --type`. At about 2.5 s and 0.95 GB per call, the cost is too high for these frequent
  commands. Trigger: the per-call editor cost drops, through batching or a persistent
  editor session. Until then, the `_init` difference stays a disclosed known difference.
  Other commands move one by one, when a need appears.

### 6. One support floor: Godot 4.6

gda's whole support floor becomes Godot 4.6: Headless operations, Live operations and the
editor context. There is no floor per context or per route. Reasons, strongest first:

1. One floor keeps one compatibility statement.
2. CI tests `4.6-stable` only, so nothing below 4.6 is verified.
3. The later editor routes need 4.6 (`EditorSettings.get_shortcut`).

A supporting slice raises the floor before the editor-context channel lands. ADR-0003
carries the Outcome note.

### 7. Rules for later growth (no code in the first scope)

- **Routes.** Route 1 is the official editor API, and the first scope uses only route 1.
  Route 2 is an editor shortcut, looked up by name through `EditorSettings.get_shortcut`
  and delivered through `Viewport.push_input`. Route 3 drives the GUI tree.
- **Route selection.** Routes 1 and 2 are isolated modules. The route is selected
  statically, before the operation acts. An operation uses route 2 only when it has no
  route-1 implementation on the running engine, and it never retries route 2 after route
  1 has run.
- **Route-2 results.** Every route-2 operation checks an observable postcondition,
  because `push_input` returns nothing. The `editor_route` result field arrives with the
  first route-2 operation.
- **Route 3** is an explicit helper, built only with an operation that needs it, and
  never an automatic fallback: focus a dock, or confirm a dialog that the same operation
  opened. Between 4.4.1 and 4.6.3, 23 of 482 shortcut names were removed, and 365 of 817
  distinct menu-item texts were removed (an upper bound, because dynamic entries are
  included).
- **Trigger for route 2:** a need admitted under ADR-0025 that route 1 cannot cover. That
  slice amends ADR-0025's out-of-scope clause for the editor GUI.
- **References.** An editor-context command that saves a scene or resource writes what
  the editor writes, `uid=` included. Runtime-context commands keep ADR-0036's path-only
  references. The first scope saves no scene or resource.
- **Plugin mode.** The payload's operations depend only on `EditorInterface` and the route
  modules, not on their host, so a later EditorPlugin host can run them in a human-opened
  editor or in a daemon-held editor. No plugin host is built until a trigger occurs: a
  need for a low-latency persistent session, or a need to co-drive with a human editor.
  Measured: `set_plugin_enabled` works in the headless host, and plugin callbacks run
  there.

### 8. Glossary

CONTEXT.md gains `Editor context`, and `Live operation` stops using that name for the
human editor's state it excludes. Each slice updates the terms whose behaviour it changes:
`Project scan`, `Import evidence`, `Headless launch`, `User-data placement`,
`Project-code execution surface` and `Shared step`. This record also corrects
`Project-code execution surface` for the scenes that the editor layout reopens on
today's import pass and native export.

## Considered options

1. **Keep the import pass for both commands.** Rejected: `project scan` keeps a second
   engine, and `resource import` keeps settling from gda's port of the engine's test,
   when the editor context answers both in one process.
2. **An EditorPlugin in a human-opened editor** (godot-mcp-pro's model) as the host.
   Rejected for the reasons in ADR-0017: it needs a human and a window. The plugin seam
   (decision 7) keeps it open as a later host.
3. **A persistent editor in `gda-daemon`.** Not now: it needs a session model (single
   writer, relaunch), and it is the path that the frequent commands wait for (decision 5).
4. **A floor per context** (editor 4.6, headless 4.4). Rejected by the project owner: one
   floor.
5. **A persistent root per project**, to save about 0.3 s. Rejected: it adds a
   location policy, cleanup and state across one-shot calls. A caller that wants reuse
   passes `--user-data-root`.
6. **An editor-context lock.** Rejected: no other Headless operation takes one, and a
   single-writer rule belongs to a persistent session.
7. **A visible dialog as a verdict.** Rejected: a project with one broken enabled plugin
   would fail every scan, while the scan result is complete.
8. **Route 3 as an automatic fallback.** Rejected: the menu texts change much more than
   the shortcut names, and a GUI action after route 1 has run can repeat a side effect.
9. **Pin the language by seeding the editor settings file.** Rejected: the `--language`
   flag does the same with no settings file and no setting key.

## Consequences

- **Schema delta.** `project scan` and `resource import` publish `kind: editor` instead
  of `import`, and `import` leaves the `kind` values. The shapes of their input and
  result models do not change; the field descriptions that name the import pass change.
- **Execution surface.** `project scan` stops starting the project's plain autoloads,
  because no second engine runs. The `@tool` scripts of the scenes that the editor layout
  reopens still run, as they do on today's import pass. The payload is gda code. No new
  trust axis (ADR-0009).
- **The user's real Godot directories.** `project scan` and `resource import` stop
  rewriting the user's editor settings, and a call that fails or times out stops leaving
  a recovery-mode lock there. By default, the native export keeps the real directories,
  because its templates live under the same data directory; `--user-data-root` moves its
  data directory, and the template lookup with it (#840). As measured on `--import`, its
  editor boot rewrites the editor settings file, and an export that fails or that gda
  kills can leave `.recovery_mode_lock`, so Project Manager offers recovery mode the next
  time the project is opened. The export path was not measured through gda. No fix is
  planned, because the effect is recoverable: the user can decline recovery mode, and
  only `--recovery-mode` starts the editor in it. It is re-evaluated on a real report, or
  when the export path is reworked.
- **Cost.** An editor-context call costs about 2.5 s and 0.95 GB on a warm project
  (4.6.3, macOS) with no reopened scene, plus about 0.3 s for a new root.
- **A payload error waits for the timeout.** The editor does not exit on a script error.
- **Unverified.** `-e --script` on Linux and Windows (the nightly `--import` and export
  legs boot the editor on both, which is indirect evidence only); the Linux and Windows
  directory variables (engine source only); more than one pair of concurrent editor
  processes; the first scope on `4.6-stable`, which CI installs; the cost and behaviour
  when the editor layout reopens scenes, beyond one scene on macOS; and the export-side
  effects above.
- **Validation that binds the slices.** The channel slice proves on the real engine that
  the classes reported equal the class index on disk after a rename, that a plain
  autoload does not run, that the private root is removed after a success and after a
  timeout, and that a stand-in for the user's real Godot directories is not written. The
  `resource import` slice proves that a corrupt asset settles as `failed` and that a cold
  request settles each asset that the engine imports from the engine's answer.

## Not decided here

- The first route-2 consumer.
- Editor-way instancing for `node add --type` and `resource create --type` (decision 5).
- A persistent editor session and its session model.
- Export through the editor context, and moving the export's editor state out of the real
  Godot directories.
- Ending a run early on a payload script error.
- Where a self-contained editor build keeps its data.

## Relation to other ADRs

- ADR-0001: one-shot headless processes — kept; the editor context is one-shot.
- ADR-0002: the payload reports through the same sentinel, and the child-stderr rule
  (#803) carries the dialog disclosure.
- ADR-0003: the floor becomes 4.6 everywhere; ADR-0003 carries the Outcome note.
- ADR-0009: the same trust boundary; ADR-0009 carries the Outcome note.
- ADR-0010: a further execution mechanism for Headless operations; ADR-0010 carries the
  Outcome note. The native export stays on mechanism 2.
- ADR-0017: the one-shot editor context is in scope; attaching to a human-opened editor
  stays out. ADR-0017 carries the Outcome note.
- ADR-0018 and ADR-0020: the sole-driver stance and the session single-writer rule,
  unchanged.
- ADR-0023: the descriptor's `kind` gains `editor`.
- ADR-0025: unchanged now; the route-2 slice amends it (decision 7).
- ADR-0031: `script run` stays in the runtime context.
- ADR-0032: the `--editor` launch shape that its first rejected option lacked now exists;
  tier 3 stays. ADR-0032 carries the Outcome note.
- ADR-0036: the reference rule in decision 7, and a correction; ADR-0036 carries the
  Outcome note.
- ADR-0042: the private-root precedent.
- ADR-0043 and ADR-0045: the payload and the channel are placed under their module rules
  by the channel slice.
