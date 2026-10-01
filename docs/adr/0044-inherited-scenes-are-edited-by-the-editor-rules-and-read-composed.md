---
status: accepted
---

# Inherited scenes: gda edits them under the editor's rules and reads them composed

An **inherited scene** is a `.tscn` whose root node line carries `instance=ExtResource(...)`
and no `type=`. The scene starts from another scene's tree — its *base* — and stores only
what it changes: property overrides on the base's nodes, nodes of its own, and connections
of its own. It is how a Godot project shares one tree and its scripts across variants
(`BaseEnemy.tscn` → `Goblin.tscn`, `Orc.tscn`) and specializes the rest. The editor creates
one through *New Inherited Scene*; gda has no command for it, and whether gda can work with
one at all was the question of 2026-09-30.

The answer, measured the same day (Godot 4.6.3, macOS, gda at main `ccee96424`), is
"mostly, with four holes and one missing door". This record states what the format and
the engine allow, what gda does today, and the decisions that #1049, #1050, #1051 and
#1052 carry out. Engine line numbers are at `4.6.3-stable`.

## Context

### What the format and the engine do

- **The root carries the base.** On instantiate, a scene whose state names a base scene
  instantiates the base as its root and marks that root with the base's `SceneState`
  (`scene/resources/packed_scene.cpp` L227-L236). On pack, a root that carries that mark
  makes the packer load the base and emit it as the root's `instance=` (L1355-L1361). The
  mark is `Node::set_scene_inherited_state` / `get_scene_inherited_state`
  (`scene/main/node.cpp` L2778 / L2784), which `Node::_bind_methods` (L3768) does not
  bind: no script can set or read it.
- **Inherited nodes are stored typeless, as overrides.** The packer stores a node's class
  only when no instance or inherited state stands behind the node; otherwise it records
  that the node came from an instantiation (`TYPE_INSTANTIATED`, L1050-L1062), and
  `SceneState::get_node_type` returns an empty name for such a node (L1886-L1892). That
  empty name is the `type: ""` gda's static read shows today. A node with no changed
  property or group gets no entry at all.
- **Deletion and reorder of an inherited node are not representable.** On instantiate,
  only a node the scene adds — an instance, a typed node, or the root — is added to the
  tree and placed (L512-L544); an override entry only sets properties on a node the base
  already created. No entry removes a base node, and no entry places one: `index` is
  saved for every node of an inherited scene (L820-L829) and applied only when a node is
  added (L543-L544).
- **Connections from the base or an instance are not stored, so their removal is not
  representable either.** The packer skips a connection that exists in the inherited
  state or in an instance state up the owner chain (L1235-L1236, L1281-L1282) and strips
  `CONNECT_INHERITED` from the ones it stores (L1319).
- **The editor refuses what the format cannot record.** `SceneTreeDock::_validate_no_foreign`
  (`editor/docks/scene_tree_dock.cpp` L2337-L2364; renamed `_validate_no_foreign_selected`
  on 4.7) has two branches. A node whose owner is not the edited scene — a node inside an
  instanced child — is refused with *"Can't operate on nodes from a foreign scene!"*
  (L2341-L2345). In an inherited scene, a node the inherited state resolves by path is
  refused with *"Can't operate on nodes the current scene inherits from!"*
  (L2347-L2360); the root is exempt except for a type change. The guard gates erase,
  reparent (to an existing or a new node), move up and down, rename, cut, change type,
  make local and load-as-placeholder. Duplicate is not gated.
- **The editor creates an inherited scene in C++.** `EditorNode::load_scene(...,
  p_set_inherited)` instantiates the base with `GEN_EDIT_STATE_MAIN_INHERITED`, sets the
  mark, and clears the scene file path (`editor/editor_node.cpp` L4792, L4803-L4808).
  GDScript has no equivalent: the mark is unbound, and packing an instantiated base
  without it stores every base node as the new scene's own, typed — a flattened copy.
- **What a script can read.** `get_node_instance` (bound, L2437) returns the base scene
  for the parentless root of an inherited scene (L1910-L1926), so
  `get_node_instance(0).get_state()` reaches the base's state on every 4.x that ADR-0003
  supports; `scene_store._packed_scene_root_type` already resolves the root type through
  it. `get_base_scene_state()` (L2429) returns the same state but is bound only from 4.5
  (engine commit `a71f670d7d`; declared and unbound at `4.4-stable`), so it is
  unavailable at ADR-0003's 4.4 headless floor. `get_node_path` (L2433),
  `get_node_index` (L2439) and the `get_connection_*` readers (L2443 on) are bound;
  `find_node_by_path` (L1493) is not.
- **The header the saver writes.** The text saver writes `[gd_scene format=3]` — no
  `load_steps`; `uid=` only when a UID is registered for the path, which a headless gda
  process never has (ADR-0036) — then the external resources, then one `[node ...]` line
  per stored node, with `instance=` on a node that instantiates a scene
  (`scene/resources/resource_format_text.cpp` L1789-L1804, L2069). The loader accepts a
  node line without `unique_id` (L197-L215); the engine assigns one on the first re-save.

### What gda does today (verified 2026-09-30 at `ccee96424`)

gda keeps an inherited scene intact without knowing what it is: every mutating node
command instantiates with `GEN_EDIT_STATE_MAIN` (`scene_store._load_for_mutation`) and
re-packs (`scene_store._repack_and_save`), and the packer re-emits the base from the
root's mark. A hand-written three-line scene:

```
[gd_scene format=3]

[ext_resource type="PackedScene" path="res://BaseEnemy.tscn" id="1_base"]

[node name="Orc" instance=ExtResource("1_base")]
```

loads. `scene list` reports it with `root_instance_path`, `root_instance_status:
resolved` and the base's root type; `scene get` shows the root with those markers;
`node set --node Sprite` writes an override entry and the root keeps `instance=`; `node
add` adds a local node (`OrcOnly`, saved with `index`) and a local child under an
inherited node (`Shape/UnderShape`, saved with `parent_id_path`); `scene validate` and
`scene preflight` pass; a `script run` oracle that instantiates the scene sees the base's
children with the override applied. `node duplicate` of an inherited node and `script
attach` to one were verified on the same shape in the first probe.

Four things do not hold:

1. **`node remove` on an inherited node reports success.** The inherited node stays;
   nothing can record its deletion. It is worse than a no-op when the node has local
   descendants: removing `Shape` freed the local `Shape/UnderShape` with it, so the file
   lost that entry while `Shape` stayed. The same reported success with no effect
   happens for a node inside an instanced child of a plain scene
   (`node remove --node Hud/Sprite`).
2. **`node move` on an inherited node reports success.** A reparent leaves the node where
   the base put it and its overrides are gone (the engine prints an owner warning). A
   same-parent reorder leaves the node where the base put it too; only the `index` of
   sibling override entries is rewritten.

   > **Outcome (2026-09-30, #1049):** re-measured on the reproduction #1049 records
   > (`Goblin.tscn` with an override on `Sprite`, a local `GoblinOnly` and a local
   > `Shape/UnderShape`; gda code as at `ccee96424`), items 1 and 2 understate what the
   > reported success did to the file. Item 1: `node remove --node Shape` also rewrote
   > `GoblinOnly`'s `index` from `3` to `2`, so the runtime order changed from `Sprite,
   > Shape, Hitbox, GoblinOnly` to `Sprite, Shape, GoblinOnly, Hitbox`, beside the lost
   > `Shape/UnderShape` entry. Item 2: a reparent does not lose the node's overrides, it
   > forks the node. `node move --node Sprite --to GoblinOnly` dropped the root-level
   > `Sprite` override entry and added a second, local, typed node, `[node name="Sprite"
   > type="Sprite2D" parent="GoblinOnly" index="0"]`, that carries the `modulate`
   > override; at runtime the inherited `Sprite` stays under the root without it, and
   > `GoblinOnly`'s `index` was rewritten from `3` to `2` as in item 1. Both edits, and
   > the rest of items 1 and 2, now return `cannot_target_foreign` with the file
   > byte-identical (#1049).

3. **`node disconnect-signal` on a connection the base declares reports success.** No
   `[connection]` entry can express the removal; the oracle sees the connection made.
4. **`scene get` and `node list` see only the scene's own state.** They list the override
   entries, typeless, and the local nodes whose parent has an entry; `Shape`, `Hitbox`
   and `Shape/UnderShape` are absent, and a fresh inherited scene lists `children: []`.
   Meanwhile `node set --node Shape` addresses that node, so the listing no longer names
   what the node commands accept — which the catalog promises for `node list`. A scene
   whose base is absent does not load at all: both reads return `not_a_scene` (exit 4),
   `scene list` reports null root fields, and `scene validate` names the missing file as
   a `missing_resource` on `.`.

And the missing door: **`scene create` cannot make one.**

The first three share one cause with each other and with the editor's guard: the format
cannot record the edit, so "success" is what the packer says by omission. The fourth is
a projection that stops at the scene's own state. The missing door is the C++ door with
no script-side equivalent.

## Decision

Six decisions. The implementation issues own the code, the tests and the docs deltas;
the decisions bind them.

### 1. gda mirrors the editor's guard, from the two sources the editor reads

Whether the scene may edit a node is decided by the editor's two branches, each from the
source the editor reads for it:

- **Inherited node**: its normalized path is declared by a scene in the base chain —
  decided from the STORED states, never from the instantiated tree. gda walks the chain
  from the scene's own state through `get_node_instance(0).get_state()`, the route
  `scene_store._packed_scene_root_type` already takes and the one bound on every 4.x
  ADR-0003 supports (`get_base_scene_state()` reads the same state and is bound only from
  4.5), and takes the union of the node paths each state in the chain declares,
  normalized the way gda normalizes state paths today. This is what `find_node_by_path`
  does inside the engine; that method is not bound, and under `GEN_EDIT_STATE_MAIN` an
  inherited node and a local node share the root as owner, so the tree cannot tell them
  apart.
- **Instance-internal node**: its owner is not the scene root — the engine's own check,
  read from the instantiated tree the mutation path already holds. The stored states
  cannot answer this one: an instanced child is one entry, and its internals are in no
  state of the chain.

One helper answers both questions, and answers them for connections too: a connection is
foreign when a state in the base chain, or the instance state that owns both endpoints,
declares it (`get_connection_*` per state). The helper lives beside the stored-tree
projection and node addressing, in the `scene_store` concept module (ADR-0043), because
#1049, #1051 and #1052 all read it and no second walk may grow.

`node remove` and `node move` — both forms, including a same-parent move without
`--index` — refuse a foreign node before touching the tree, in an inherited scene and in a
plain one, and the file stays byte-identical.

> **Outcome (2026-10-01, #1064):** one function in the `scene_store` module now answers
> the Foreign question for every write: `_refuse_foreign_write`. #1049 and #1054 had
> grown three helpers, and each call site chose its helper. Now each of the nine call
> sites names the write it makes (`scene_store.Write`, one value per write), and the
> guard selects the rule from it:
>
> - a structural write (`REMOVE`, `MOVE`) reads the instance owner and the
>   inherited-node map of the base chain, and does not read the editable flag;
> - `DISCONNECT` reads the states that declare the connection;
> - every other write reads the instance owner, with the editable exemption of #1054.
>
> The guard records the refusal and returns true. The rules and the messages did not
> change: a base-and-head corpus of 189 calls over the nine sites was byte-identical
> (#1064's pull request). The existing `cannot_target_root` checks for remove, move
> and duplicate stay at their call sites, before the Foreign guard.

### 2. One error code: `cannot_target_foreign`

Both branches, on nodes and on connections, report one registered operation code,
`cannot_target_foreign` (category `operation`, source `operation`, exit 4), beside
`cannot_target_root`. The caller's next move is the same in every case: edit the scene
that declares the target — or, for an inherited node, override its properties in this
one. What differs — which scene declares it, and whether an override is open — goes in
the message, which names that scene's `res://` path, in the shape of `cannot remove
Shape: the node is declared by res://BaseEnemy.tscn, which this scene inherits — edit
that scene, or override its properties here`, and for an instance-internal node `cannot
remove Hud/Sprite: the node is inside res://BaseEnemy.tscn, instanced at Hud — edit that
scene`. Two codes would make the caller branch on a distinction it cannot act on
differently.

The ADR-0002 registry row, added by #1049 with the code's other registration sites:

| Code | Category | Source | Exit Code | Meaning |
|------|----------|--------|-----------|---------|
| `cannot_target_foreign` | `operation` | `operation` | `4` | A structural edit targeted a node or connection another scene declares — one the scene inherits, or one inside an instanced child — which the scene file cannot remove, reparent, reorder, or disconnect. |

The spelling takes the editor's word: "foreign" is what the editor calls a node the
edited scene does not own. This record widens it to both branches, and the glossary term
(decision 6) is defined that way.

> **Outcome (2026-10-01, #1054):** #1054 widened the row quoted above. The code also
> refuses six writes the file cannot record: `node set` and `script attach` on a node
> inside an instanced child that the scene root does not hold as editable, `node add`
> and `node move --to` under such a node, `node duplicate` of its child, and `node
> connect-signal --from` it. The meaning now reads: "A write targeted what the scene
> file cannot record: a structural edit — remove, reparent, reorder, disconnect — on a
> node or connection another scene declares (one the scene inherits, or one inside an
> instanced child), or any write on or under a node inside an instanced child that the
> scene root does not hold as editable." Those refusals use this decision's instance
> shape plus a second route: `cannot set Hud/Sprite: the node is inside
> res://BaseEnemy.tscn, instanced at Hud — edit that scene, or mark the instance's
> children editable in the editor`. No new error code.

### 3. What stays allowed

The refusal covers the structural edits the format cannot record, and nothing else. On
an inherited node: `node set` (an override entry), `script attach`, `node
connect-signal` (a connection the scene declares), `node add` under it (a local child,
placed by `index`), `node duplicate` (the copy is local and typed) — each verified to
reach the file (Context). On a local node of an inherited scene:
everything, including a move among inherited siblings — the engine saves `index` for
every node of an inherited scene and applies it when the local node is added (verified:
`node move --node OrcOnly --to . --index 0` puts it first at runtime). The root of an
inherited scene keeps `cannot_target_root` for the edits that need a parent.

On an instance-internal node this record decides only the structural edits above. The
other writes are not one case — some reach the file and some do not (Not decided here
lists what was verified) — and they are the instanced-children contract's question
(#399, #400) in any scene, not an inherited-scene one.

### 4. Static reads compose the chain, still without instantiating

`scene get` and `node list` report the composed tree: the base's nodes first, recursively
down the chain, then the scene's own state on top.

- An override entry merges into the base node it addresses and shows the base's type;
  the typeless entry is the SAME node, not a second one.
- A local node is placed under its composed parent by the engine's rule, in state order:
  `index` applied when `0 <= index < child_count - 1` once the node is added, else
  appended. A local child of an inherited node is therefore listed, where today it is
  dropped.
- Every inherited node that is not the root carries `inherited_from`: the `res://` path
  of the scene in the chain that declares it (on a two-level chain the grandparent's
  nodes name the grandparent). A local node omits the field. The root keeps
  `instance_path` / `instance_status` exactly as #400 defined them.
- Internals of an instanced child — in the base or in the scene — stay unexpanded and
  marked as today.
- A base that does not resolve keeps today's failure: the engine does not load such a
  scene, so `scene get` and `node list` return `not_a_scene` (exit 4) as they do at
  `ccee96424` (Context, item 4). gda does not guess a tree it cannot read.
- The human rendering marks inherited nodes, so both modes tell the same story.

This reads the chain through decision 1's route on states that are already loaded — the
base is a dependency of the inherited scene and comes in with it — and instantiates
nothing.
ADR-0009's state-read guarantee and README's "read without instantiating" stay true as
written. The inherited-node set the marker uses is the helper of decision 1.

> **Outcome (2026-10-01, #1051):** one inherited node carries no `inherited_from`: an
> instanced child a base declares whose scene is missing. The loader stores that entry
> as neither typed nor instanced, so decision 1's helper reads no scene as adding it;
> only the per-scene text recovery shows it is an instance, and the read reports that
> marker (`instance_status: missing`) without a declaring scene. Kept rather than
> adding a second declaring rule; the catalog, the field description and the skill
> say so.

### 5. `scene create --inherits` writes the header the saver writes

`gda scene create PATH --inherits res://Base.tscn [--root-name NAME]` writes the
three-section text above: `[gd_scene format=3]`, one path-only
`[ext_resource type="PackedScene" path="..." id="..."]`, and a root line
`[node name="NAME" instance=ExtResource("...")]`. No `uid`, no `unique_id`, no
`load_steps`: the engine assigns unique ids on the first re-save and reads the rest as it
reads its own output.

- `--inherits` and `--root-type` are mutually exclusive and one is required — the rule
  and wording pattern of `node add --type` / `--instance`: on argv, exit 2 with no engine
  spawned; through `--params-json`, `invalid_params`.
- `--root-name` defaults to the target filename stem, as it does today. The editor keeps
  the base root's name; gda keeps its own convention, and the name is an override the
  file records on the root line.
- Validation before any write reuses the ladder `node add --instance` applies:
  `already_exists`, `missing_dependency` (the base path does not exist), `not_a_scene`
  (the base is not a scene). The base path is normalized to `res://` like every scene
  path.
- After the write, the command loads the file back and confirms the engine reads it as
  inherited — `get_node_instance(0)` on its state returns the base, decision 1's route.
  A file the engine does not read that way
  is `save_failed` and is removed. The read-back is the load the static reads perform and
  adds no point to the `Project-code execution surface`.
- The result carries `inherits` and the `root_type` resolved from the base's root, by the
  resolution `scene list` already uses.

This is gda's one text-authored scene header. ADR-0036 describes gda as authoring
through `ResourceSaver` and gets a dated Outcome note. ADR-0009 rejected "text-level
`.tscn` editing that bypasses engine semantics" as a hardening route for untrusted
projects; this is not that. The header is what the engine's own saver writes for such a
scene, the engine is asked to read it back before the command reports success, and
nothing else in gda edits scene text.

> **Outcome (2026-09-30, #1050):** validation is by load, not through the helper
> `node add --instance` uses, because that helper instantiates the base and so runs the
> base scripts' `_init`. The command checks that the base exists (`missing_dependency`)
> and is a PackedScene (`not_a_scene`), then loads it (`missing_dependency` when the
> load fails) and never instantiates it: the ladder above without its instantiate rung.
> A `.scn` target with `--inherits` is refused like a selector violation, before any
> engine spawn (exit 2 on argv, `invalid_params` through `--params-json`): the header is
> a `.tscn` text shape, and a `.scn` holding text does not load.

### 6. Glossary

CONTEXT.md gains `Inherited scene` and `Foreign node`. The second names the two branches
that the guard, the `inherited_from` marker and the connection check share.

## Considered options

1. **Instantiate the base and pack it** for creation. Rejected: without the mark the
   packer stores every base node as the new scene's own, typed — a copy that stops
   following the base (Context). The mark is unbound.
2. **Detect inherited nodes from the instantiated tree.** Rejected: under
   `GEN_EDIT_STATE_MAIN` inherited and local nodes have the same owner, and the mark is
   unbound. The stored state is the one readable source, and it is what the editor's
   guard reads.
3. **Two codes** (`cannot_target_inherited`, `cannot_target_instanced`). Rejected: the
   caller's move is the same; the declaring scene's path in the message carries the
   difference. One row, one constant, one test row.
4. **Record what the format can and warn about the rest** for remove and move.
   Rejected: the format records nothing of a deletion or of a base node's position, and
   today's reported success already lost a local subtree. The editor refuses; gda
   refuses.
5. **Compose the read by instantiating**, as `node get` does. Rejected: that runs every
   script's `_init` on a read, against ADR-0009's state-read guarantee and README's
   statement, and the stored states already hold the answer.
6. **Editable children** (`[editable path=...]`) as gda's route into an instanced
   child's nodes. Not decided here: the guard's instance branch stays the editor's, and
   an editable instance keeps its own packer semantics (L797-L799) that this record does
   not model.
7. **Raise the headless floor to 4.5** so the guard may read `get_base_scene_state()`.
   Rejected: the route decision 1 takes reads the same state, is bound at ADR-0003's 4.4
   floor, and is already in use in `scene_store`; a floor amendment would buy nothing.

## Consequences

- **A reported success becomes a refusal.** A caller that scripted `node remove` or
  `node move` against a foreign node, or `disconnect-signal` against a foreign
  connection, gets `cannot_target_foreign` (exit 4) where it got a result before. That
  result never described the file; this corrects the contract rather than narrowing it.
  `--json` consumers branch on the code; the message says which scene to edit.
- **Static reads grow, for inherited scenes only.** `children` fill in with the base's
  nodes, override entries show their type, and `inherited_from` appears on non-root
  inherited nodes. A plain scene's output is byte-identical to today. Schema delta: one
  optional field on the shared node model, omitted when absent.
- **`scene create` changes shape.** `root_type` becomes optional in the input model (the
  `required` list changes) and `inherits` joins the input and the result, omitted when
  absent, so existing dispatch payloads and results stay byte-identical.
- **One new error code**, registered at its sites under the ADR-0002 registry tests.
- **Docs.** Catalog: the scene-root shared rule gains the second rule; the `node remove`,
  `node move` and `disconnect-signal` bullets and the #64 mutation-integrity paragraph say
  what an inherited scene keeps and refuses; "Static instance reporting" and the "what a
  scene DECLARES" sentence gain the inherited half; the `scene create` row and section
  gain `--inherits`. README: the `scene create`, `node remove` and `node move` rows get
  their one gotcha, with the three localized READMEs and the i18n stamp. SKILL.md: one
  compact paragraph on inherited scenes. Two comments are corrected: the move op's claim
  that a reparent preserves inherited and override children, and the theme op's claim
  that every scene write goes through `ResourceSaver`.
- **Trust surface unchanged.** No new `Project-code execution surface` point: the guard
  reads stored state and the owner the mutation path already has, the composed read
  instantiates nothing, and the creation read-back is a load.
- **Verification that binds the slices.** Each defect above is an e2e regression that
  fails at `ccee96424`; the composed read is checked node for node and in order against a
  `script run` oracle on a two-level chain; every path `node list` reports round-trips
  through `node set`; the `.tscn` is byte-identical across every refusal.

## Not decided here

- Editable children as a gda feature (option 6).
- The non-structural writes on an instance-internal node, in any scene. Verified on
  2026-09-30 (Godot 4.6.3; `Host.tscn`, a plain scene with `Hud` instanced from
  `BaseEnemy.tscn` and no `[editable]` entry; gda code as at `ccee96424`): `node set`
  and `script attach` on `Hud/Sprite`, `node add --parent Hud/Sprite` and `node
  connect-signal --from Hud/Sprite` each report success and the file gains no entry;
  `node move` of a local node `--to Hud/Sprite` reports success and the file LOSES
  that local node's entry. The packer skips a node the root does not own, with its
  subtree (L797-L799), and the connection parser skips a source inside an instance
  (L1137-L1140). `node duplicate` of `Hud/Sprite`, `node connect-signal --to
  Hud/Sprite` and `node disconnect-signal` of that connection reach the file: the
  duplicate op re-owns the copy to the scene root, and a connection whose source the
  root owns stores its target by path (L1302-L1310). A refusal of every write on that
  shape was recorded on PR #1053's first review round and withdrawn on the second
  (2026-09-30): it read L797-L799 as covering every write, which the three saving
  writes disprove, and no requirement asked for it. The five reported successes are a
  mutation-integrity defect of the instanced-children contract (#399, #400; the #64
  boundary), to be decided per operation and outside this record: tracked in #1054.

  > **Outcome (2026-10-01, #1054):** decided in #1054 by the packer's condition. A
  > write is refused with `cannot_target_foreign` when the node it writes to is inside
  > an instanced child that the scene root does not hold as editable: the target of
  > `node set` and `script attach`, the parent of `node add`, the target of `node move
  > --to`, the source of `node connect-signal`, and the source's parent of `node
  > duplicate` (a sixth case: `node duplicate --node Hud/Hitbox/HitShape` reported
  > `Hud/Hitbox/HitShape2` and the file did not change). The internals of an editable
  > instance (`[editable path="Hud"]`) stay writable, one level deep, and the three
  > saving writes above are unchanged. Decision 2's refusal of the structural edits
  > does not read the editable marker, and is unchanged.
- A rename operation, and a dependents check for `scene delete` when the deleted scene
  is another scene's base.
- Changing the root type of an inherited scene, which the editor also refuses; gda has
  no such operation.

## Relation to other ADRs

- ADR-0002: the registry row and the operation-source registration. ADR-0004: the
  model-driven schema delta.
- ADR-0003: the headless floor (4.4) stands; decision 1 reads the base chain through a
  route bound there (option 7).
- ADR-0009: state reads execute no project code — kept. Its rejection of text-level
  editing is not the case here (decision 5).
- ADR-0033 and ADR-0036: references by `res://` path; ADR-0036 carries the Outcome note.
- ADR-0040 / ADR-0043: `scene_store` owns the helper and the projection; the node and
  scene groups consume them.
- ADR-0025: an inherited scene is the same object the surface already edits — no new
  command group, one new option.
- #400 (instance markers on static reads), #56 (structural edits), #64 (mutation
  integrity) and #399 (instanced children): the paragraphs this record extends.
