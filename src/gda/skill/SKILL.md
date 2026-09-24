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
- Pass `--project DIR`, set `GDA_PROJECT`, or run inside the project directory.
  The project must contain `project.godot`. Use an explicit project when a
  script or asset depends on `res://` or project autoloads.
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
4. Use `export list` to select a preset, then `export run`. If needed, use
   `export smoke` on the built artifact. A smoke run proves only what that
   bounded process observed; it does not prove that the game completed its
   intended task.

When `scene create` uses a `Control-derived` root, it writes zero anchors
and zero offsets. A root with no intrinsic minimum size renders as a zero-size
rect; a root with an intrinsic minimum size renders at that minimum instead,
not at viewport size. Set `anchor_right` and `anchor_bottom` to `1` with
`node set`, then confirm the layout with `game rect` in an Engine session.
For a `Control` inside a `Container`, change minimum size, size flags, or
the container layout instead of offsets.

### Writable `user://` in restricted environments

Headless runs already send the engine log to a private temporary file.
If a script must write to `user://` and the default application-data
directory is not writable, give that invocation a writable data root:

```bash
gda --user-data-root /writable/gda-data script run res://tests/all.gd --project game --json
```

This moves both the log and `user://`. Inspect `engine_data_path` or
`log_file` before treating a failed save as a game defect. Scope the
redirect to the calls that need it: Godot also finds export templates under
its application-data directory, so a redirected export can hide templates
installed on the host.

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
   an available desktop session. Stop with `gda daemon stop`.

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
gesture. A lone press does not activate a Godot `Button`.

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
