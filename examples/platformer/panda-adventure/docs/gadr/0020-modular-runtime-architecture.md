---
status: accepted
---

# Organize the runtime as Add-ons, Systems, Content, and UI

The former `src/` buckets grouped files by technical type but did not make the
dependency direction visible. UI controllers, application flow, domain rules,
configuration types, and development tools could appear to be peers even when
their responsibilities were different.

The shipped runtime now uses four module roots with one dependency direction:

```text
UI -> Content -> Systems -> Add-ons -> Godot
```

Each runtime file may depend on its own module or a module to its right. Upward
communication uses signals, callbacks, or values returned from a lower module;
lower modules do not locate or load higher modules.

- `addons/` holds reusable library-like support that is independent of the game
  domain. This is the broad architectural meaning of Add-on, not only Godot
  editor plug-ins. It currently contains the committed gda harness and the
  generic structured logger.
- `systems/` holds game rules, state transitions, invariants, and their shared
  state types. Systems are independent of concrete scenes, UI, and Content
  configuration classes. Controllers pass the scalar values a rule needs.
- `content/` holds the concrete application: controllers, configuration and
  generated data, gameplay scenes, presentation adapters, and game assets. It
  selects and coordinates Systems into playable behavior.
- `ui/` holds screen-space surfaces and the `GameShell` composition root. UI
  binds to Content's public application surface, observes `run_ended`, and sends
  retry intent downward through `LevelController.retry()`. When Content accepts
  that intent, the Game Shell reloads its composition scene.

The Game Shell instances `content/scenes/gameplay.tscn`, the HUD, and the End
screen. Gameplay contains no UI nodes or UI resource paths. `LevelController`
injects the Player into spawned enemies and exposes `player_node()` for shell
binding; runtime code no longer discovers the Player through a global group.
The existing `gravity_affectable` and `time_dilatable` groups remain because
they represent open-ended capability membership rather than a unique object
dependency.

Development-only code remains outside the runtime chain. The in-game editor is
under `tools/editor/`, may depend on runtime modules, and is excluded from
exports. Python asset and balancing packages, scripts, tests, and documentation
keep their established toolchain roles. No `gyms/` folder is added: this project
has durable tests and development tools, but no temporary interactive sandbox
that would benefit from that lifecycle.

The JSON authority and generated-Resource workflow from gADR-0000 are unchanged.
Configuration Resources that describe concrete game content live in Content;
`StatsConfig` lives in Systems because it is the shared state shape used by
domain rules. The committed `GdaHarness` autoload remains unchanged.

Consequences:

- Directory placement communicates responsibility and allowed dependencies.
- The Game Shell is the single runtime composition point for UI and Content.
- A small static test rejects upward runtime resource paths, global class
  references, unresolved UID loads, and dependencies on the development editor.
- Adding a global event bus, interface layer, or wrapper for every cross-module
  call is unnecessary. Direct downward calls and narrow upward signals are the
  default.
