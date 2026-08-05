---
name: design-godot-modular-architecture
description: Design and review modular Godot project architectures around Add-ons, Systems, Content, and UI, with acyclic downward dependencies and indirect upward communication. Use when structuring a new Godot project, separating reusable systems from authored content, reviewing architectural coupling, deciding where scenes, scripts, and resources belong, or planning an incremental modularization.
---

# Design Godot Modular Architecture

## Goal

Design the smallest architecture that gives the current project clear ownership, useful reuse boundaries, and one-way dependencies.

Default to four project roots:

- `addons/`: reusable technical libraries.
- `systems/`: reusable game rules and domain state.
- `content/`: application flow and project-specific content.
- `ui/`: presentation and interaction.

Use domain-driven design as a broad guide: keep related language, rules, and state together; give each rule and state one owner; and separate reusable game rules and state from application-specific coordination. Do not require formal DDD patterns or vocabulary unless they solve a demonstrated problem.

## Keep Dependencies Pointing Down

Order the layers from lowest to highest:

1. Godot Engine
2. Add-ons
3. Systems
4. Content
5. UI

Allow code to depend on its own layer or a lower layer:

- UI may depend on Content, Systems, Add-ons, and Godot.
- Content may depend on Systems, Add-ons, and Godot.
- Systems may depend on Add-ons and Godot.
- Add-ons may depend on Godot and, when necessary, other explicitly declared Add-ons.

Keep same-layer dependencies explicit and acyclic. Do not let lower-layer code reference a higher-layer script, type, scene, resource, or path.

Follow Godot's "call down, signal up" rule: use direct calls for downward requests and signals for upward notifications. Use callbacks, observers, or publish/subscribe only when they fit the relationship better.

Keep `project.godot` limited to project settings, main-scene selection, and Autoload registration. Use the main scene or a small startup script as a thin project bootstrap that creates and connects modules, injects resources or callbacks, and hands off to application flow. Keep rules and application flow out of the bootstrap itself.

Treat scene instantiation as a dependency. Compose Content and UI in the bootstrap or in a UI-owned composition scene that may depend downward on Content. Do not embed UI scenes in Content scenes; inject references and connect signals at the composition point.

Treat Autoload as a registration and lifetime choice, not as a layer. Keep each Autoload script under its owning root and apply the same dependency rules. Use an Autoload only when global lifetime or a unique instance is justified; prefer bootstrap-created and injected instances otherwise. Do not use Autoload to bypass boundaries or as a default service locator or event bus. If an event channel is an Autoload, place its contract in the lowest layer that defines the messages and keep it unaware of subscribers.

## Place Code and Assets

Create each root when its responsibility exists. For a small project, an absent root is fine as long as existing responsibilities are not mixed. Treat the child modules and file names below as placement guidance, not as a required directory template.

### Add-ons

Use **Add-on** in the broad sense of a reusable library module. It is not limited to a Godot plugin with `plugin.cfg` or an `EditorPlugin` implementation, though those plugins are one kind of Add-on.

This is a local architectural convention, not a claim that every reusable library is a Godot plugin. Separate first-party libraries from third-party plugins by ownership, using subdirectories or naming when the distinction would otherwise be unclear.

Use `addons/` for reusable technical capabilities that do not encode project-specific rules or concepts.

Typical contents include:

- Input mapping, buffering, and device helpers.
- Generic camera controllers, camera shake, and target-following tools.
- Serialization, configuration, and file-access helpers.
- Object pools, caches, and generic resource loaders.
- Reusable state-machine or behavior-tree runners.
- Math, randomization, geometry, and pathfinding algorithms.
- Generic data structures.
- Signal, callback, or event-dispatch utilities.
- Generic audio playback and bus controls.
- Tween, timeline, and animation-playback helpers.
- Logging, profiling, and debug tools.
- Editor plugins, importers, and project checks.
- Third-party Godot plugins.

Keep an add-on independent when practical. First-party Add-ons should declare their dependencies on other Add-ons. Keep those dependencies visible and acyclic, and treat the connected set as one reuse unit.

Treat third-party plugins as external packages: record their version and dependency set, and do not assume control over their internal architecture.

Separate editor-only plugin code from runtime code when an Add-on contains both. Do not make a runtime build depend on editor-only APIs.

Move project-specific rules out of Add-ons.

### Systems

Use `systems/` for stable game rules and domain state that can support different Content.

Typical systems include:

- AI perception, decisions, target selection, and behavior execution.
- Combat, hit resolution, damage, effects, and cooldown rules.
- Navigation, path requests, movement constraints, and position queries.
- Stats, attributes, conditions, and modifier rules.
- Item, container, equipment, and exchange rules.
- Interaction, selection, triggering, and availability rules.
- Time progression, turns, schedules, and phases.
- Resource production, consumption, trading, and economy rules.
- Objective state and completion rules.
- Dialogue state and branch conditions.
- Saveable game state.

A System may contain GDScript classes, Resources, reusable scenes or nodes, state queries, public operations, and signals that report state changes.

Name and group Systems using the project's own language. Do not create a fixed internal structure simply to match an architectural pattern.

Let Systems use Add-ons and collaborate through small, clear APIs. Keep their dependency graph acyclic.

Keep these out of Systems:

- Project-specific scene sequences.
- One-off level or event scripts.
- Concrete character, item, or location data.
- Authored animation, audio, art, or text assets.
- UI controls and display formatting.
- Coordination that exists for only one Content setup.

Do not let a System load Content or UI paths. When it needs a higher-level scene, resource, factory, or response, inject it from Content or the project bootstrap.

### Content

Use `content/` for the application layer and authored project content. Let it choose, configure, and coordinate Systems into concrete behavior.

Typical contents include:

- Application entry points and flow controllers.
- Scene transitions and session flow.
- Levels, maps, regions, and environment scenes.
- Concrete characters, objects, and other entity scenes.
- Concrete items, abilities, and interaction data.
- Objectives, scripted events, and content-specific sequences.
- Dialogue text, choices, voice, and localization data.
- Animation clips, AnimationLibraries, and AnimationTree configurations.
- Music, ambience, sound effects, and voice assets.
- 3D models, meshes, textures, materials, shaders, and visual effects.
- System configuration and tuning Resources.
- PackedScenes, Resources, and asset assemblies.
- Scripts that connect several Systems into one application behavior.

Organize Content by feature, level, region, chapter, or asset category as the project requires.

Application flow and authored assets share Content because both are project-specific and fall outside the reuse boundary of Systems and Add-ons. Within Content, separate them by owner and reason to change.

Let Content call public System operations, configure System instances, connect Systems, and inject concrete resources. Keep reusable rules in Systems rather than repeating them in Content.

Expose the application operations, state, and notifications needed by UI.

### UI

Use `ui/` for presentation and interaction. Let UI turn Content or System state into visual, textual, and interactive feedback, and turn user actions into application actions.

Typical contents include:

- HUDs and status bars.
- Character stats, attributes, and condition panels.
- Dialogue panels, dialogue boxes, and choice lists.
- Popups, modals, toasts, tooltips, and notifications.
- Main, pause, and settings menus.
- Inventory, equipment, journal, and objective panels.
- Maps, navigation cues, and target indicators.
- Action prompts, input hints, and context menus.
- Progress bars, meters, cooldown displays, and status icons.
- Reusable buttons, lists, tabs, and selection controls.
- UI themes, fonts, icons, and UI-only assets.
- Focus movement and keyboard or controller navigation.
- UI transitions, control animation, and UI sound effects.
- Presenters, view models, formatters, and binding scripts where they help.
- Accessibility and interface scaling controls.
- Debug and developer interfaces.

Let UI read public state and subscribe to Content or System signals. Send application-changing actions through Content's application entry points. Allow direct UI-to-System commands only when the design intentionally has no Content coordinator for that action. Keep only presentation state in UI, such as focus, expansion, and local transition progress.

Do not place game rules or application flow in UI. Do not let UI mutate System internals or own state that belongs to Content or Systems.

## Separate Different Parts of One Feature

Do not place every artifact for one topic in the same area. Place each part according to its responsibility.

| Topic | Add-ons | Systems | Content | UI |
| --- | --- | --- | --- | --- |
| AI | Generic behavior runner | Perception and decision rules | Concrete behavior setup and tuning data | Debug or status display |
| Combat | Timers, pools, collision helpers | Hit, damage, and effect rules | Concrete actors, abilities, effects, and encounter setup | Status bars, cooldowns, and action cues |
| Stats | Generic containers or serialization | Stat state and modifier rules | Initial values and concrete configuration | Character stats panel and formatting |
| Dialogue | Data loading and localization helpers | Dialogue state and branch conditions | Text, choices, voice, and authored flow | Dialogue panel, choice list, and text animation |
| Animation | Generic playback or tween helpers | Game state that drives animation choice | Clips, AnimationTrees, and scene configuration | Control transitions and UI animation |
| Audio | Generic players and bus controls | Rules that produce meaningful sound events | Music, ambience, effects, and voice assets | Volume settings, subtitles, and playback feedback |
| Input | Device and action-map helpers | Game actions independent of devices | Bindings for the current application flow | Controls, menus, and input hints |
| Save data | File access and serialization | Saveable game state | Save/load flow and save-game assembly | Save slots, load menu, and result feedback |

Use this split to keep one owner for each rule and state, avoid hard-coded assets in Systems, and avoid project language in Add-ons.

## Workflow

### 1. Pin Down the Current Need

Establish:

- The architecture problem to solve now.
- The evidence that the problem exists.
- The project size, collaboration needs, expected reuse, and expected rate of change.
- The observable result that would count as an improvement.
- Existing behavior and constraints that must stay intact.
- Future possibilities that remain out of scope.

Mark unsupported expectations as assumptions. Do not expand the design to satisfy them.

### 2. Inspect the Project

Read the project's architecture docs, ADRs, and project conventions when they exist. Inspect only the evidence needed for the current decision:

- Directory contents and actual responsibilities.
- Main scenes and startup wiring.
- Autoloads.
- `extends`, `class_name`, `preload()`, `load()`, and resource paths.
- `get_node()`, `$`, and `%` node paths.
- Exported Node, NodePath, Resource, and PackedScene references.
- Scene and Resource references.
- Scene inheritance and scene instantiation.
- `@tool` scripts and other editor-only code.
- Parent-child lifecycle assumptions.
- State owners and mutation paths.
- Signals, callbacks, groups, and event channels.

Do not infer architecture from directory names alone.

### 3. Map Responsibilities

Classify each relevant responsibility:

- Put domain-neutral, reusable technology in Add-ons.
- Put reusable rules, domain state, and state transitions in Systems.
- Put application coordination and authored material in Content.
- Put display and interaction in UI.

Classify by reason to change and reuse boundary, not merely by file type. When a responsibility appears to fit two areas, identify which area owns the underlying rule or state and let the other consume it.

### 4. Trace Dependencies

Draw the source dependencies required by the current behavior. Check for:

- Upward references.
- Cycles.
- Lower layers loading higher-layer paths.
- Autoloads that bypass ownership boundaries.
- Global type names, node groups, or string identifiers that hide coupling.
- Several modules owning the same rule or state.
- Scene and Resource references that cross a forbidden boundary.

Do not create an interface for every call. Add indirection only when it protects a real boundary, supports a needed substitution, or enables upward communication.

### 5. Choose Communication

Apply "call down, signal up" with the simplest mechanism that preserves the dependency direction:

- Direct call for a downward request.
- Signal or observer for one-to-many upward notification.
- Callback for a small, local response supplied by higher-level code.
- Publish/subscribe for communication that genuinely needs independent publishers and subscribers.

Define a message or callback in the lowest layer that can describe it without knowing its consumers. Do not use events to hide unclear ownership.

### 6. Check the Design

Check completeness against the current goal:

- Give every required behavior an owner.
- Make every required dependency and communication path possible.
- Cover relevant state changes, lifecycle, and failure paths.
- Include hidden Godot dependencies from scenes, Resources, Autoloads, and global types.

Check orthogonality:

- Give each rule and state one clear owner.
- Keep application flow separate from reusable game rules and state.
- Let one area change without forcing unrelated areas to change.
- Group modules by reason to change.

Check DRY:

- Define each rule, state, public interface, and message shape once.
- Keep multiple representations only when they serve distinct needs.
- Share code only when its meaning and reasons to change are also shared.

Prefer a small local duplication over a shared abstraction that couples unrelated modules.

### 7. Make the Smallest Useful Change

Keep, simplify, move, split, merge, defer, remove, or test a design idea according to current evidence.

Prefer small, reversible changes that establish the needed boundary. When modularizing an existing project, migrate through working slices rather than requiring a complete directory rewrite before the first verification.

## Scale the Rules to the Project

For a small project, clear ownership and a few visible dependencies may be enough.

Add finer System boundaries, dedicated public interfaces, more event channels, automated dependency checks, or stricter CI only when team size, reuse needs, or observed coupling justify their cost.

Once the project adopts a dependency rule, apply it consistently. Scale the number of mechanisms, not the meaning of the boundaries.

## Output

Return only the parts that help answer the request:

1. Current goal, evidence, and assumptions.
2. The smallest sufficient architecture or change.
3. Responsibility placement across Add-ons, Systems, Content, and UI.
4. Required dependency and communication paths.
5. Actionable violations or trade-offs.
6. Incremental implementation or migration steps.
7. Verification suited to the size of the change.

Use a diagram or dependency table only when it makes an important relationship easier to understand. Do not create extra artifacts to make the design appear more complete.
