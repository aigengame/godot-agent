---
name: gda
description: Use the gda CLI to build, inspect, validate, and export Godot projects without opening the editor, or to inspect and control a running game through gda-daemon. Use when an agent builds or modifies a Godot game, or the user asks for gda or Godot automation.
---

# gda

`gda` is an agent-facing CLI for Godot. Use headless operations to create and
inspect scenes, nodes, scripts, resources, shaders, themes, and project settings;
validate or run scripts and scenes; and export artifacts. Use live operations to
inspect a running game, inject input, capture the viewport, and read diagnostics
or performance data. Headless operations support Godot 4.4+ on all platforms.
Live operations use `gda-daemon` with Godot 4.6+ on macOS or Linux.

## Configure and discover

- Set `GDA_GODOT` to the Godot executable, or pass `--godot PATH`.
  If a command reports `binary_not_found`, find the Godot executable or ask the
  user for its path, then use it as above.
- Pass `--project DIR`, set `GDA_PROJECT`, or run inside the project directory.
  The project must contain `project.godot`. Use an explicit project when a
  script or asset depends on `res://` or project autoloads.
- Keep the same engine and project for the related calls of one workflow.
- Use `gda --version --json` to identify the installed CLI and its source in a
  long session. Use `gda info --json` to check the Godot engine.
- Use `gda --help` for command groups, `gda <group> --help` for a group's
  commands, and `gda <group> <command> --help` for usage. Use
  `gda <group> <command> --schema` for that command's arguments, JSON result,
  and errors. `gda schema` describes the full installed surface. Consult
  these sources for exact options and fields instead of assuming this skill is a
  command catalog.

Pass `--json` on operations, for example
`gda scene validate res://main.tscn --project game --json`. Read the one JSON
object on stdout; engine output goes to stderr. On failure, branch on the
structured `error.code` and inspect any `evidence`; do not parse
`error.message`. An exit code of zero does not always mean the requested check
passed:

| Operation | Check in the successful result |
| --- | --- |
| `scene validate`, `script validate` | `valid`; `false` is not a pass. |
| `scene preflight` | `status` and `started`; static validation does not boot the target scene. |
| `script run`, `export smoke` | Child `exit_status` and diagnostics; use `--strict` when non-zero status or a recognized shutdown leak must fail the command. |
| `game set` | `verified`; `false` means the observed read-back differs. Follow up with `game get` or a domain-specific observation when the side effect matters. |

For precision-sensitive values, inspect the result or read-back. Godot can
change a decimal value while parsing it; `gda` refuses values that the parser
would destroy. Consult the relevant command schema for accepted value forms
and limits.

## Headless workflow

With no project yet, run `gda project create DIR --name NAME --json` first.
DIR must be a new directory in an existing parent, or an empty directory;
dot-prefixed entries such as `.git` do not count. The new `project.godot` sets
only the name, so set the main scene and other settings with `project set`.
Then use DIR as the project.

Run `gda project scan --json` on a fresh checkout or a project the editor
never opened, and after you add, rename or delete a `class_name` script: the
engine finds a project `class_name` only through the index a scan writes, and
gda does not check whether that index is current.

1. Create or edit a scene with `scene`, `node`, `script`, and `resource`
   commands. Use `script attach` to bind a script to a node; generic
   `node set --property script` is refused. Create assets used by
   `preload("res://...")` before you attach the script. Supply a `res://`
   Resource path when assigning a Resource-typed property.
2. Run `scene validate` and `script validate` for the changed files. Check
   their `valid` verdicts. `scene validate` checks dependencies and scripts,
   but does not prove that the target scene starts.
3. Run `scene preflight` to boot the target scene for a bounded interval.
   Check its startup verdict and diagnostics. Use `script run` for a
   project test script; inspect the child status even when `gda` succeeds.
4. Use `export list` to select a preset. Optionally inspect it with
   `export get`, then run `export run`. If needed, use `export smoke` on the
   built artifact. A smoke run proves only what that bounded process
   observed; it does not prove that the game completed its intended task.

When `scene create` uses a `Control-derived` root from `--root-type`, it writes
zero anchors and zero offsets. A root with no intrinsic minimum size renders as
a zero-size rect; a root with an intrinsic minimum size renders at that minimum
instead, not at viewport size. Set `anchor_right` and `anchor_bottom` to `1`
with `node set`, then confirm the layout with `game rect` in an Engine session.
For a `Control` inside a `Container`, change minimum size, size flags, or
the container layout instead of offsets. A root from `--inherits` keeps the
base's anchors and offsets.

For a variant of a base scene, use `scene create PATH --inherits BASE`, not
`node add --instance`: the new scene's root is the base's root. In the variant,
override inherited nodes with `node set` and add its own nodes; edit or remove
inherited nodes in the base. `scene get` and `node list` show the variant's
composed tree and mark inherited nodes with `inherited_from`; an inherited
instance whose scene is missing carries no mark.

`export run` checks the export templates itself before it exports, and
refuses with `export_templates_missing` when they are not available.
`--mode pack` needs no templates. `export get` is optional inspection. Give
it the same engine, project, preset, and data root (`--user-data-root`) as
`export run`:

- `templates_installed: false` means that the `templates_version` directory
  is missing under `templates_root`. Then a non-null `templates_root_host`
  means that the host has these templates but the data root hides them; a
  null value means that they are not installed.
- `templates_installed: true` means only that the version directory exists.
  It does not prove that the preset's platform can export.

To recover, put matching templates, including the files for the preset's
platform, under `templates_root`. With a data root, you can instead select
another data root, or run without one where the environment permits.
Template readiness does not prove that an export succeeds or that the
Export artifact runs.

### Data root in restricted environments

A headless run sends the engine log to a private temporary file. Godot can
still write to its data directory during engine initialization, including
for a validation. If that directory is not writable, select a writable data
root. The global option comes before the command group:

```bash
gda --user-data-root /writable/gda-data scene validate res://main.tscn --project game --json
```

The data root moves the engine data directory (`user://` and the export
templates) and the engine log. The editor configuration and cache locations
depend on the platform and can stay in place; on Linux they do not move.
Judge the impact from the operation verdict and the engine diagnostics. A
directory warning does not by itself make a successful operation invalid.
`script run` reports `engine_data_path` and `log_file`; inspect them before
you treat a failed `user://` save as a game defect.

- Use one data root for the engine-launching headless operations of one
  restricted workflow.
- Use a separate data root for each invocation that runs at the same time.
  Each launch truncates the one engine log under a data root.
- Do not set the data root (`GDA_USER_DATA_ROOT`) for unrelated commands.
- Do not give `export smoke` a data root unless it refuses with
  `user_data_unwritable`. Without one, each smoke run creates a private data
  root, so no `user://` state carries from one smoke run to the next.
- `--user-data-root` does not reconfigure an Engine session that the daemon
  manages.
- A successful validation under a data root does not prove that the export
  templates are available there.

### Advanced Godot usages

**Scene inheritance.** One base scene holds the tree and its scripts. A
variant made with `scene create PATH --inherits BASE` keeps that tree and
stores only what it changes: overrides on the base's nodes, and nodes of its
own. Keep the logic in the base and specialize the visuals and values in each
variant. The commands and the rules are in the variant paragraph above.

**Resource-based components.** A `class_name` script that `extends Resource`
holds a behavior's data and logic, decoupled from the scene tree: the behavior
lives in a file that any node can hold and call, not in a node at a path, so
the agent defines and tunes it without a scene edit, and swaps it without
changing the node tree. `project scan` registers the class, `resource create`
writes the `.tres`, and `node set --value res://….tres` links it to a node
export typed with that class.

A shared component is the default: the `.tres` stays linked in every scene
file, and an edit of the `.tres` reaches all of them. For a per-instance
copy, choose one of two options:

- **Local to scene** (`resource set --property resource_local_to_scene
  --value true`): the engine gives each scene instance its own copy when it
  instantiates the scene, before any `_ready`; the nodes of one instance
  share that copy, and a nested resource that is local to scene is copied
  too. On that copy `get_local_scene()` returns the scene root and the
  engine calls `_setup_local_to_scene`; a `duplicate()` copy gets neither.
  The risk: when the node that holds the component is one an inherited scene
  takes from its base, or the root of an instanced child, a re-save of that
  scene by any gda write or by the editor stores the copy in its file as an
  embedded `sub_resource`. The link to the `.tres` is lost in that file, a
  later edit of the `.tres` does not reach it, and nothing reports it.
- **`duplicate()` in the owner's script**, for example in `_ready`: the
  `.tres` stays linked in every scene file, and the script makes the copy at
  runtime. The script then owns what the engine owned: a child's `_ready`
  runs before its parent's and sees the shared `.tres`; two nodes of one
  instance that duplicate separately do not share. On Godot 4.5+,
  `duplicate(true)` copies an embedded sub-resource but keeps a nested `.tres`
  shared, and `duplicate_deep(Resource.DEEP_DUPLICATE_ALL)` copies the nested
  `.tres` too.

Rule of thumb: use `duplicate()` for a component on a node that the re-save
above can reach, and local to scene for a resource the engine must set up
per scene. The copy semantics above are the engine's, not a gda guarantee.

## Live workflow

A live run needs a main scene. Set `application/run/main_scene` or pass a
valid `--scene res://...` to `daemon start`. An explicit `res://` scene
also bypasses an unresolved `uid://` main scene.

1. Start the daemon with `gda daemon start --project game --json`. This can
   install the gda harness and update `project.godot`; inspect the change.
   The Engine session starts when a live operation needs it.
2. Run `gda daemon wait-ready --project game --json` before read-only
   diagnostics. Inspect `clean_start` and `startup_diagnostics`. A serving
   session can still have a scene script that failed to compile. A null
   `clean_start` means the startup log was unavailable, not that it was clean.
3. Discover runtime node paths with a bounded `game tree --max-depth N` or
   `game find` query. Narrow with `--root`; a truncated result or a bounded
   empty search does not prove absence. Then use `game get`, `game rect`,
   or other live commands on the exact path.
4. Use `input` for interaction, `diag errors` and `logger tail` for
   diagnostics, and `perf` for measurements. Start the daemon with
   `--windowed` if you need `screen capture`; a rendered capture requires
   an available desktop session.
5. Stop with `gda daemon stop`. This stops the daemon and its Engine
   session, but the gda harness stays installed. To remove the gda harness
   installation, run `gda daemon uninstall` after `daemon stop`. A
   disposable project copy is an optional way to keep the harness out of
   the source project. You do not need to uninstall before `gda export run`:
   it removes the harness for the export and restores the project's prior
   harness state. Other export routes do not remove it.

For a windowed launch, `live_windowed_unavailable` means skip rendered
checks in this environment. `live_windowed_permission_denied` means retry
outside the restriction before deciding whether the host can render.

After updating gda, stop and start the daemon before using live commands.
Repeating `daemon start` updates the installed harness but does not reload
the code in the running game.

A `live_timeout` discards the Engine session. The next live operation starts
a new game, so do not assume that earlier runtime changes still exist.

Input has two injection routes, reported as `injection_route`. The default
`input action` uses `action_state` to change the polled action state; it
does not send an event to `_input`, `_unhandled_input`, or `_gui_input`.
A key or mouse command uses `viewport_event` to send an event through the
viewport. Use `input action --as-event` only when an event handler must
receive that action rather than the mapped key:

| Injection | `Input.is_action_pressed` | `_input` / `_unhandled_input` | `_gui_input` |
| --- | --- | --- | --- |
| `input action` | yes | no | no |
| `input action --as-event` | no | yes | yes (focused Control) |
| `input key` of the mapped key | no | yes | yes (focused Control) |

The table describes eligible delivery under normal propagation and
consumption rules, not proof that a handler ran. For UI activation, use
`input mouse-click` or `input tap` to send a complete press/release
gesture. A default `BaseButton` activates on the release; `action_mode` or
subclasses such as `MenuButton`/`OptionButton` can activate on press.

To verify an interaction:

1. Find out whether the game polls input state or handles input events.
   Select the route from the table.
2. Find the runtime target with a bounded `game tree` or `game find` query.
3. Inject the matching input.
4. Read the expected game state, for example with `game get`. This read is
   the proof. An injected gesture alone does not prove that the intended
   handler or gameplay action ran.

`game rect` reports coordinates relative to the Control's canvas. A
transformed `CanvasLayer` or an active `Camera2D` can make them differ from
click coordinates. Do not take click coordinates from the pixels of a
viewport capture.

`script run` runs your script as written. It does not add coordinate
conversion, gesture completion, or event timing to the script's own
`push_input()` calls. Your tests must establish those details and the
actual UI layout. Input that a script sends is separate from input that
gda injects with `input` commands into an Engine session. See Godot's
[InputEvent guide](https://docs.godotengine.org/en/4.6/tutorials/inputs/inputevent.html).

A `screen capture` is evidence only when it shows the intended state:

- Use the `--await-*` predicate to capture when the relevant state holds.
  The predicate must represent the visible state. Text kept on a hidden
  `Label` is not sufficient.
- Use `--await-events` to trigger a short-lived state and capture it in one
  operation.
- Use `--settle-frames` when the game draws the state later. A settle moves
  the capture later than the predicate's first match. The earlier state can
  be gone by then.
- Inspect the image. When timing matters, also inspect the returned frame
  counters and predicate evidence.
- Do not assume that one settle count works for every state. Process
  frames are not a fixed wall-clock duration.

If the game needs structured records in `logger tail`, resolve the harness
by node path and check that the daemon launched the session. Do not refer to
the `GdaHarness` global in game code: a project or export without the harness
cannot parse that name.

```gdscript
var harness := get_node_or_null("/root/GdaHarness")
if harness != null and harness.is_daemon_launched():
    harness.gda_log("info", "player spawned", {"hp": 100})
else:
    print("player spawned")
```
