---
name: design-verifiable-playtest
description: >-
  Design and review player-facing Godot playtests that use a maintained Model Source
  Package, Experiment Specifications, and gda-balancing execution. Use when game
  balance or a gameplay mechanic needs a small playable product for direct player
  testing and feedback. Do not use for a general Godot game or a CLI-only tutorial.
---

# Design Verifiable Playtest

## Goal

Design the smallest player-facing product that makes one gameplay question easy to
understand and evaluate.

A verifiable playtest serves two audiences:

- A player can understand the feature, make a meaningful choice, see its cost and
  effect, reach a natural outcome, and provide feedback without learning
  gda-balancing internals.
- A maintainer can prove that the visible result came from the maintained source and
  the real gda-balancing execution path, not from a second implementation in Godot.

Do not trade one form of verification for the other. Keep maintainer evidence out of
the player experience.

## Start With the Player Question

Define one primary question before you design modules or screens. Examples include:

- Does a reward frequency feel fair?
- Can a player compare damage with resource cost?
- Can a player understand when periodic damage is calculated?
- Does a build change produce a visible gameplay difference?

Record:

- the target player;
- the feature under test;
- the choice or action the player performs;
- the difference the player should notice;
- the natural completion condition; and
- the feedback that can answer the question.

Combine several features only when the player must experience them together to make
the required judgment. Do not design the UI from Kernel, Language Definition Bundle,
Formula, Operation, Experiment Specification, or artifact fields.

## Use Familiar Player Language

Use terms in this order:

1. established terms from the game genre;
2. terms that the relevant player community already uses; and
3. a plain description of the actual behavior.

Check comparable games and player material when a term is uncertain. If no stable
term exists, use a direct description. Do not invent a technical-sounding mechanic
name to make the feature appear distinct. An application title can be creative, but
the mechanic labels must remain clear.

Player-facing rules must explain the parts that affect the observed behavior:

- what happens;
- when it happens;
- how often it happens;
- what it costs;
- which condition applies; and
- whether later steps recalculate, retain, inherit, or reset the value.

Check the copy against the real state sequence. A short sentence is not clear if it
hides cast-time calculation, per-step recalculation, state carry-over, or a trial
reset.

## Match Player Expectations

Follow established interaction and visual conventions when they fit the feature:

- Use familiar colors, labels, icons, and screen positions for common game state.
- Show an action's cost and effect together.
- Give immediate visual and text feedback for a state change.
- Make a reset visible when comparison trials are independent.
- Make state carry-over visible when actions are sequential.
- End on a real gameplay outcome, not an internal sample count or run count.
- Offer restart and feedback as separate choices after the terminal outcome.
- Show a visible retry action after a recoverable failure.
- Show the absolute feedback-file path after a successful save.
- Copy the same feedback JSON that the application saves.

Accept gameplay input only when the action is visible and enabled. Content must also
reject actions outside the allowed gameplay phases. A hidden button is not a complete
input guard.

Add adjustable options only when they help answer the player question. Do not add
settings only to make the application look more interactive.

## Use a Readable MVP Presentation

Prefer a low-cost presentation unless visual fidelity is part of the question:

- blockout shapes;
- semantic colors;
- clear state labels and values;
- short, visible Tweens; and
- distinct preparation, action, response, and terminal states.

Blockout art does not excuse unclear hierarchy or missing feedback. Add detailed art,
audio, or animation only when it materially affects the player judgment.

## Hide Technical Mechanisms

Do not expose these concepts in player UI or gameplay System interfaces:

- Kernel or Language Definition Bundle;
- Model Source Package or Experiment Specification;
- Formula, Runtime, Event queue, logical time, or Snapshot;
- Metric, artifact, identity, diagnostic, or provenance; and
- HTTP, readiness record, process capability token, Execution session, or Experiment
  revision.

Add-ons and Content can use these concepts internally. UI and Systems must receive
application-owned gameplay values.

Show a player-facing problem and a next action when execution fails. Put detailed
diagnostics and reproduction details in a maintainer log or a maintainer-only section
of the feedback record. Never copy the process capability token or the complete
readiness record into an error, log, Content value, or UI value.

## Keep One Authored Data Source

Each maintained example owns one Model Source Package and the necessary Experiment
Specifications. CLI and playtest are separate consumers of those authored sources:

```text
CLI -------+
           +--> [Model Source Package + Experiment Specification] --> gda-balancing
Playtest --+
```

Apply these rules:

- Let CLI and playtest read the maintained files directly.
- Do not copy those files into a CLI or playtest delivery directory.
- Do not generate a fixed case-data layer for Godot.
- Do not add a playtest-only configuration authority or partial-update format.
- Write edited Experiment Specifications and generated artifacts to a temporary or
  run directory.
- For a player change to Experiment-owned input, derive a complete, immutable
  Experiment revision. Send the complete Experiment Specification value to the
  service, not an implicit patch.
- For a player change to a model definition, submit a complete Model Source Package
  and an initial Experiment Specification to create a new Execution session. Do not
  encode a model definition as an Experiment Specification override.
- Store a named preset as a shared Experiment Specification when CLI and playtest
  both need that preset. Do not hard-code it in both consumers.

The CLI is usually the cheapest deterministic tracer. A polished CLI tutorial does
not have to precede the first playable vertical slice, but both paths must continue to
use the same maintained source.

## Use the gda-balancing Service Boundary

Godot must use the public local gda-balancing Execution HTTP API for the live
data path.

Do not:

- import the Python Runtime into Godot;
- reimplement gda-balancing numeric or Runtime semantics in GDScript;
- add a game-specific HTTP route;
- add game fields to the generic execution client; or
- add a playtest-specific Runtime.

Use the current public contract first. Do not treat complete runs of an Experiment
Specification as a permanent service limit. When a real application needs a new
generic operation, extend the gda-balancing service as a separate capability and then
consume it from the playtest. This rule also applies when a required Model Source
Package change cannot use the current service. Do not hide the gap with a Godot
special case. Do not add a speculative service extension without an application need.

### Local Process Boundary

The reusable execution Add-on owns:

- executable discovery;
- child-process startup and shutdown;
- the readiness record and protocol compatibility;
- the process capability token;
- generic HTTP requests;
- Execution session and Experiment revision handles;
- timeouts and forced cleanup; and
- sanitized transport errors.

Prefer an explicitly configured gda-balancing executable. Use the current `PATH` as
the fallback. Do not guess a repository `.venv`. Do not silently replace an invalid
explicit path. Preserve that failure until the application can show a retry action.

Do not bundle Python or add an exporter such as PyInstaller for a repository-local
playtest unless distribution is a real requirement with its own service-lifecycle
design.

## Apply the Godot Module Architecture

Before you assign Godot responsibilities, read and apply
`$design-godot-modular-architecture`. This skill adds the player-facing product and
gda-balancing boundaries; it does not replace the general Godot architecture skill.

Use the established dependency direction:

```text
Godot Engine <- Add-ons <- Systems <- Content <- UI
```

Use direct calls for downward requests and signals for upward notifications. Keep
same-layer dependencies explicit and acyclic.

A multi-playtest project commonly has this shape:

```text
playtest/
|-- addons/
|   |-- gda_balancing_client/
|   `-- playtest_feedback_file/
|-- systems/
|   `-- <gameplay-capability>/
|-- content/
|   `-- <feature>/
|-- ui/
|   `-- <feature>/
`-- apps/
    `-- <feature>/
        |-- main.gd
        `-- main.tscn
```

`apps/` is an optional delivery directory for composition roots. It is not a fifth
responsibility layer. All non-composition responsibilities still belong to Add-ons,
Systems, Content, or UI.

### Application Bootstrap

Give each playable an explicit, thin composition root. It creates the concrete UI
composition, Content entry point, Systems, and Add-ons; injects dependencies; connects
signals; and starts the application.

Keep source locations, document interpretation, gameplay rules, HTTP behavior, and
retry flow out of the bootstrap.

### Add-ons

Place reusable technical capabilities in Add-ons. Keep the gda-balancing client game
neutral. Its public interface must not contain Reward, Combat, Effect, or other
feature fields.

A generic feedback-file Add-on can write JSON and return an absolute path. The
feature Content still owns the questions and feedback meaning.

### Systems

Systems receive only validated gameplay values. They can own reusable gameplay state,
state transitions, and gameplay phases that do not duplicate gda-balancing semantics.

Systems must not:

- parse Model Source Package, Experiment Specification, HTTP, artifact, or artifact-set
  values;
- store revision, identity, or provenance data;
- recalculate a result that gda-balancing already produced; or
- accept a universal Dictionary that includes technical fields.

### Content

Content is the deep module between technical execution and the player product. It
owns:

- maintained source selection;
- document loading;
- classification of each player change by its authored authority;
- projection of Experiment-owned input into complete Experiment revisions;
- submission of a complete Model Source Package and initial Experiment Specification
  to create a new Execution session for model-definition changes;
- Execution session, Experiment revision, and run coordination;
- returned artifact-set interpretation;
- validation of relationships that gameplay consumes;
- projection into application-owned gameplay values;
- atomic publication, failure, and retry flow;
- feature-specific feedback; and
- maintainer provenance that remains hidden from players.

Validate the complete relationship before Content publishes gameplay state. Field
presence and wire types do not prove that returned values agree with each other.

### UI

UI owns player presentation and interaction: controls, state displays, copy,
localization, input hints, settings, Tweens, feedback questions, and player-facing
failure states.

Send application-changing actions through Content. Do not call the HTTP client from
UI. Do not interpret Standard Schema data in UI.

Keep a shared shell limited to behavior that several real applications use with the
same meaning. Keep feature controls, feature copy, and feature questions in their
owning UI module.

## Deepen Only Proven Reuse

Do not create a general playtest framework for the first application. Extract a
shared module only after real consumers show the same meaning, lifecycle, failure
behavior, and reason to change.

Common candidates can include:

- the gda-balancing execution client;
- feedback-file writing;
- display and language preferences;
- a common player shell;
- launch support; and
- test-run support.

Do not introduce a universal gameplay payload, application registry, central feature
switch, generic Content module, global event bus, or process-management framework
without demonstrated consumers. Prefer small local duplication when similar code has
different meaning.

## Workflow

### 1. Define the Experience

Specify the player question, choices, visible differences, state sequence, terminal
outcome, and feedback questions. Review the mechanic terms and copy before you design
the full screen.

### 2. Pin the Maintained Source

Identify the exact Model Source Package, Experiment Specifications, CLI entry, and
playtest Content loader. Classify every adjustable value by its authored authority.
State how Experiment-owned changes create complete Experiment revisions, how
model-definition changes create a complete Model Source Package and a new Execution
session with an initial Experiment Specification, and where temporary output goes.
Remove any copied source or generated case authority.

### 3. Design the Modules and Data Path

Apply `$design-godot-modular-architecture`. Assign application responsibilities to
Add-ons, Systems, Content, or UI. Then select an optional delivery directory for the
thin composition root. Trace the complete path from player input through the local
service and back to validated gameplay state.

### 4. Prove a Real Tracer

Before you build a large UI, run the smallest real-service path that covers the risky
semantic boundary. Typical risks include:

- state transfer between consecutive revisions;
- explicit reset between independent comparison trials;
- player-option projection;
- cost, effect, and terminal-outcome agreement;
- refusal atomicity; and
- process failure and retry.

Use the real local service. A fake is not sufficient as the only integration evidence.
If the tracer finds a missing generic capability, evaluate that service gap before you
build a workaround.

### 5. Deliver a Playable Vertical Slice

The first slice must include a real launch, one player action, the authored source or
declared input required for that action, one real service run, Content validation,
System state application, visible UI feedback, and a natural continuation or
completion point. Use an Experiment revision for Experiment-owned changes. Create a
new Execution session when the Model Source Package changes.

Add more choices, the complete flow, feedback, localization, and recovery in later
working slices.

### 6. Review the Real Player Sequence

Inspect what the player sees and can do at each state:

```text
Start
  -> Preparing
  -> Ready
  -> Player action
  -> Visible cost and effect
  -> Continue or terminal outcome
  -> Restart or feedback
```

For comparison playtests, verify reset and carry-over explicitly. Do not judge the
flow from the final screenshot only.

### 7. Revisit Shared Modules

After a second real application exists, compare the implementations. Deepen only the
modules with proven shared semantics. Recheck dependencies and public interfaces after
each extraction.

## Verification

Select tests by risk. Do not add tests only to make a matrix look complete.

Use the applicable evidence:

- a source-authority check that rejects copied Model Source Package or Experiment
  Specification files;
- Godot dependency and scene-reference checks;
- checks that UI and Systems do not receive technical terms or fields;
- tests that verify that each player option updates the correct authored authority;
- System gameplay-state tests;
- UI copy, controls, input guards, reset, and terminal-flow tests;
- a real-service Add-on lifecycle test;
- refusal, process failure, invalid-path, and retry tests;
- localization-key parity checks;
- feedback file, clipboard, and absolute-path checks; and
- a critical end-to-end test that starts from the real main scene.

The critical path is:

```text
UI
  -> application bootstrap
  -> Content
  -> gda-balancing Add-on
  -> real local HTTP service
  -> exact Experiment revision
  -> validated gameplay values
  -> System and UI
  -> feedback
```

Do not replace this path with a script-existence check, a fake client, a component-only
test, schema validation, or a final-state assertion.

### Validate Relationships, Not Only Fields

Content must validate each relationship that UI or Systems rely on. Add focused
mutation tests when individually valid fields can form a contradictory result. Common
examples include:

- damage that does not match health before and after the action;
- resource cost that does not match resource state;
- a selected result that does not match its candidate;
- periodic count, order, lifecycle, or outcome that does not match the timeline;
- an independent trial that inherits prior state; and
- a refusal that still publishes gameplay state.

Do not copy the production algorithm into a reference implementation. Test the
relationship and boundary without creating a third semantic authority.

### Use Human Feedback for Human Questions

Automation can prove execution and UI state. It cannot fully decide whether terms feel
natural, feedback is timely, pacing is abrupt, or options feel meaningfully different.

Use a human-in-the-loop checkpoint only when such a question is part of acceptance.
Do not label all playtest work as HITL by default.

Record:

- misunderstood terms;
- the first point where the player pauses or gets lost;
- an outcome that differs from the player's expectation;
- an unexplained value change;
- a missing control or response;
- the perceived difference between options; and
- whether restart, retry, and feedback are easy to find.

## Output

For a new design, provide only the sections that the task needs. Cover:

1. the player question and target experience;
2. the player flow and natural completion condition;
3. mechanic terms, key copy, and rules that need explanation;
4. controls, visual hierarchy, and feedback;
5. the shared Model Source Package, Experiment Specification, CLI, and playtest map;
6. Add-ons, Systems, Content, and UI ownership, plus the optional composition root;
7. the gda-balancing Execution HTTP API data path;
8. failure, retry, reset, and state carry-over;
9. playable vertical slices;
10. automated and human verification; and
11. explicit exclusions and unresolved assumptions.

For a review, start with the player impact and reproducible evidence. Then identify the
responsibility owner and the smallest practical correction. Do not require a new
framework because of superficial code similarity, directory symmetry, or a minor
inconsistency.
